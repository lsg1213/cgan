import torch, pickle, os, pdb, librosa, joblib
import numpy as np
from torch.utils.data import Dataset, DataLoader
import torch.nn as nn
from tqdm import tqdm
import torch.nn.functional as F
from tensorboardX import SummaryWriter
import models
from utils import *
from torchsummary import summary
from glob import glob
from pytorch_model_summary import summary
import concurrent.futures as fu
from params import get_arg



def main(config):
    os.environ['CUDA_VISIBLE_DEVICES'] = config.gpus
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    
    SR = config.sr
    WINDOW_SIZE = 500 # us
    data_length = config.len
    BATCH_SIZE = config.batch
    learning_rate = config.lr
    EARLY_STOP_STEP = 15
    EPOCH = 2000
    K, m = 8, 8
    ls = 128

    ABSpath = '/home/skuser'
    if not os.path.exists(ABSpath):
        ABSpath = '/root'
    if config.name == '':
        name = f'{config.model}'
        name += f'_b{config.b}_d{data_length}' if config.feature == 'wav' else ''
        name += f'_lat{config.latency}_{config.opt}_{config.lr}_decay{config.decay:0.4}'
        name += f'_feature{config.feature}_{config.loss}'
        if config.feature == 'mel':
            name += f'_nfft{config.nfft}'
        if config.relu:
            name += '_relu'
        if config.future:
            name += '_future'
        if config.diff:
            name += f'_{config.diff}'
            name += f'_weight{config.loss_weight}'
        if config.subtract:
            name += f'_subtract'
        if config.filter:
            name += f'_filter_{config.range}'
        if config.norm:
            name += f'_norm'
        
    else:
        name = config.name
    if not os.path.exists(os.path.join(ABSpath, 'ai_model')):
        raise FileNotFoundError('path is wrong')
    tensorboard_path = os.path.join(ABSpath, 'ai_model/pytorch/test_model/tensorboard_log/' + name)
    modelsave_path = os.path.join(ABSpath, 'ai_model/pytorch/test_model/model_save/' + name)
    if not os.path.exists(modelsave_path):
        os.makedirs(modelsave_path)
    if not os.path.exists(tensorboard_path):
        os.makedirs(tensorboard_path)
    writer = SummaryWriter(tensorboard_path)
    print(name)
    # data_path = os.path.join(ABSpath,'data')
    # if not os.path.exists(data_path):
    #     data_path = os.path.join(ABSpath, 'datasets/hyundai')
    data_path = '.'
    transfer_f = np.array(pickle.load(open(os.path.join(data_path,'transfer_f.pickle'),'rb')))

    transfer_f = torch.tensor(transfer_f[::-1,:,:].copy(),device=device)
    transfer_f.requires_grad = False
    if config.feature in ['wav', 'mel']:
        accel_raw_data = joblib.load(open(os.path.join(data_path,'stationary_accel_train.joblib'),'rb'))
        sound_raw_data = joblib.load(open(os.path.join(data_path,'stationary_sound_train.joblib'),'rb'))
    elif config.feature == 'mel':
        data_path = os.path.join(data_path, f'{config.feature}_{config.nfft}_{config.nmels}')
        if not os.path.exists(data_path):
            raise ValueError('directory is wrong for to get data')
        accel_raw_data = torch.cat([joblib.load(open(i, 'rb')) for i in sorted(glob(data_path+'/*accel*.joblib'))]).unsqueeze(1) # (frames, 1, nmels, 12)
        sound_raw_data = torch.cat([joblib.load(open(i, 'rb')) for i in sorted(glob(data_path+'/*sound*.joblib'))]) # (frames, windowsize, 8)

        if accel_raw_data.shape[0] != sound_raw_data.shape[0]:
            raise ValueError(f'length of accel and sound data is not matched, {accel_raw_data.shape}, {sound_raw_data.shape}')

    

    # accel_data = dataSplit(accel_raw_data, takebeforetime=config.b, data_length=data_length, expand=True)
    # sound_data = dataSplit(sound_raw_data, takebeforetime=config.b, data_length=data_length, expand=False)
    # model = Model(accel_data.shape[1] * accel_data.shape[2], sound_data.shape[1] * sound_data.shape[2]).to(device)
    dataset = makeDataset(accel_raw_data, sound_raw_data, config, device)
    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [int(0.9 * len(dataset)), len(dataset) - int(0.9 * len(dataset))])
    

    # mel: inputs=(n_mels, 12), outputs=(window_size, 8), inch=(3), outch=(frames)
    if config.feature == 'wav':
        model = getattr(models, config.model)((config.len + config.b,), (8,), 12, config.len, config).to(device)
    elif config.feature == 'mel':
        model = getattr(models, config.model)((config.nmels, 12), (config.len,), (config.len + config.b) // (config.nfft // 2) + 1, 8, config).to(device)
    print(config.model)
    # loader = torch.utils.data.DataLoader(train_dataset, shufflt=False, batch_size=BATCH_SIZE, drop_last=False)
    # resume = torch.load(sorted(glob(modelsave_path+'/*.pt'), key=lambda x: float(x.split('/')[-1].split('_')[0]))[-1])
    # optimizer.load_state_dict(resume['optimizer'])
    # model.load_state_dict(resume['model'])
    # model.eval()
    # with torch.no_grad():
    #     for x, sound in loader:
    #         x = x.type(torch.float32).to(device)
    #         sound = sound.type(torch.float32).to(device)
    #         y = model(x)
    #         y_p = conv_with_S(y, transfer_f, config)

    # exit()
    
    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=BATCH_SIZE, drop_last=False)
    

    # criterion = nn.MSELoss()
    if config.loss == 'l1':
        criterion = nn.SmoothL1Loss()
    elif config.loss == 'l2':
        criterion = nn.MSELoss()
    elif config.loss == 'custom':
        criterion = CustomLoss()
        l1 = nn.SmoothL1Loss()
        criterion = [criterion, l1]

    if config.opt == 'adam':
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    elif config.opt == 'sgd':
        optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate, momentum=0.9)
    else:
        raise ValueError(f'optimzier must be sgd or adam, current is {config.opt}')
    # lr_schedule = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=config.decay, verbose=True)
    lr_schedule = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=config.decay, patience=1, threshold=0.001, threshold_mode='rel', cooldown=0, min_lr=0, eps=1e-08, verbose=True)
    startepoch = 0
    min_loss = 10000000000.0
    earlystep = 0
    if config.resume:
        if len(glob(modelsave_path+'/*')) != 0:
            resume = torch.load(sorted(glob(modelsave_path+'/*.pt'), key=lambda x: float(x.split('/')[-1].split('_')[0]))[-1])
            optimizer.load_state_dict(resume['optimizer'])
            model.load_state_dict(resume['model'])
            startepoch = resume['epoch'] + 1
            min_loss = resume['min_loss']
            lr_schedule.load_state_dict(resume['lr_schedule'])
            earlystep = resume['earlystep']
        else:
            print('resume fail')


        
    
    model.to(device)
    for epoch in range(startepoch, EPOCH):
        train_loader = torch.utils.data.DataLoader(train_dataset, shuffle=True, batch_size=BATCH_SIZE, drop_last=False)
        train_loss, train_custom, train_l1 = 0.,0.,0.
        val_loss, val_custom, val_l1 = 0.,0.,0.
        model.train()
        _train_loss, _train_custom, _train_l1 = trainloop(model, train_loader, criterion, transfer_f, epoch, config=config, optimizer=optimizer, device=device, train=True)
        
        train_loss += _train_loss
        train_custom += _train_custom
        train_l1 += _train_l1
        

        model.eval()
        with torch.no_grad():
            val_loss, val_custom, val_l1 = trainloop(model, val_loader, criterion, transfer_f, epoch, config=config, optimizer=None, device=device, train=False)
        
            

        writer.add_scalar('train/train_loss', train_loss, epoch)
        writer.add_scalar('train/train_l1', train_l1, epoch)
        writer.add_scalar('val/val_loss', val_loss, epoch)
        writer.add_scalar('val/val_l1', val_l1, epoch)
        if config.loss == 'custom':
            writer.add_scalar('val/val_custom', val_custom, epoch)
            writer.add_scalar('train/train_custom', train_custom, epoch)
        lr_schedule.step(val_loss)
        # lr_schedule.step()
        torch.save({
            'model': model.state_dict(),
            'epoch': epoch,
            'optimizer': optimizer.state_dict(),
            'earlystep': earlystep,
            'min_loss': min_loss,
            'lr_schedule': lr_schedule.state_dict()
        }, os.path.join(modelsave_path,f'{epoch}_{val_custom:0.4}_{val_loss:0.4}' + '.pt'))

        if np.isnan(train_loss) or np.isnan(val_loss):
            print('loss is divergence!')
            break
        if config.loss != 'custom':
            val_custom = val_loss
        if min_loss > val_custom:
            earlystep = 0
            min_loss = val_custom
        else:
            earlystep += 1
            if earlystep == 3:
                print('Early stop!')
                break

def trainloop(model, loader, criterion, transfer_f, epoch, config=None, optimizer=None, device=torch.device('cpu'), train=True):
    epoch_loss = 0.
    epoch_custom = 0.
    epoch_l1 = 0.
    if config.norm:
        acc_norm = acc_normalizer(config)
        snd_norm = snd_normalizer(config)

    if config.feature == 'mel':
        melspectrogram = torchaudio.transforms.MelSpectrogram(8192, n_fft=config.nfft, n_mels=config.nmels).to(device)
    elif config.feature == 'stft':
        stft = wavToSTFT(config, device)
        istft = STFTToWav(config, device)
    elif config.feature == 'wav' and config.filter:
        filt = bandPassFilter(config)
    
    if config.loss == 'custom':
        l1 = criterion[1]
        criterion = criterion[0]
    if train:
        data_num = len(loader)
    else:
        data_num = len(loader)
    with tqdm(loader, total=data_num) as pbar:
        for index, (accel, sound) in enumerate(pbar):
            if train:
                optimizer.zero_grad()
            accel = accel.to(device).type(torch.float64)
            sound = sound.to(device).type(torch.float64)
            if config.norm:
                accel = acc_norm(accel)
                sound = snd_norm(sound)
            if config.subtract:
                sound = -sound
            if config.filter:
                accel = filt(accel)
                sound = filt(sound.transpose(-1,-2)).transpose(-1,-2)

            if config.feature == 'mel':
                accel = melspectrogram(accel.type(torch.float64)).transpose(1,3)
            elif config.feature == 'stft':
                with ThreadPoolExecutor() as pool:
                    accel = list(pool.map(stft, accel))
                accel = torch.stack(accel)
                accel = torch.cat([accel.real, accel.imag], 1)
                if config.st2st:
                    sound = sound.transpose(-1,-2)
                    with ThreadPoolExecutor() as pool:
                        sound = list(pool.map(stft, sound))
                    sound = torch.stack(sound)
                    sound = torch.cat([sound.real, sound.imag], 1)
            
            y = model(accel)
            
            if config.feature == 'stft':
                if config.st2st:
                    y_p = y
                else:
                    y = torch.stack([y[:,:y.shape[1]//2],y[:,y.shape[1]//2:]],-1)
                    with ThreadPoolExecutor() as pool:
                        y = list(pool.map(istft, y))
                    y = torch.stack(y,0).transpose(2,1)
                    y_p = conv_with_S(y, transfer_f, config)
            else:
                y_p = conv_with_S(y, transfer_f, config)
                
            if config.loss == 'custom':
                custom_loss = criterion(y_p.type(sound.dtype), sound)
                l1_loss = 0.1 * l1(y_p.type(sound.dtype),sound)
                total_loss = custom_loss + l1_loss
            else:
                loss = criterion(y_p.type(sound.dtype), sound)
            
                if config.diff == 'diff':
                    if y_p.size(1) <= 1:
                        raise ValueError('Cannot use difference value for loss')
                    diff = get_diff(sound)
                    diff_y_p = get_diff(y_p).type(sound.dtype)
                    diff_loss = criterion(diff_y_p, diff)
                    total_loss = config.loss_weight * loss + diff_loss
                elif config.diff == 'double':
                    if y_p.size(1) <= 2:
                        raise ValueError('Cannot use double difference value for loss')
                    diff = get_diff(sound)
                    diff_d = get_diff(diff)
                    diff_y_p = get_diff(y_p).type(sound.dtype)
                    diff_y_p_d = get_diff(diff_y_p)
                    diff_loss = criterion(diff_y_p,diff)
                    diff_d_loss = criterion(diff_y_p_d, diff_d)
                    total_loss = config.loss_weight * loss + diff_loss + diff_d_loss
                else:
                    total_loss = loss

            if train:
                total_loss.backward()
                optimizer.step()
            epoch_loss += total_loss.item()
            if config.loss == 'custom':
                epoch_custom += custom_loss.item()
                epoch_l1 += l1_loss.item()
                pbar.set_postfix(epoch=f'{epoch}', total_loss=f'{epoch_loss / (index + 1):0.4}', custom_loss=f'{epoch_custom / (index + 1):0.4}', l1_loss=f'{epoch_l1 / (index + 1):0.4}')        
            else:
                pbar.set_postfix(epoch=f'{epoch}', total_loss=f'{epoch_loss / (index + 1):0.4}')
            if index == data_num - 1:
                break
        epoch_loss /= data_num
        epoch_custom /= data_num
        epoch_l1 /= data_num
        
    return epoch_loss, epoch_custom, epoch_l1
            

if __name__ == "__main__":
    import sys
    config = get_arg(sys.argv[1:])
    if config.feature == 'mel' and config.nfft > config.len + config.b:
        config.nfft = config.len + config.b
        print(f'nfft is too big to use, change nfft to {config.len + config.b}')
    main(config)