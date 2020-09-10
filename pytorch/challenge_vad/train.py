import torchvision, torch, os
import torchvision.transforms as transforms
import torchaudio, pickle, pdb
import torch.nn as nn
import torch.optim as optim
from glob import glob
from utils import *
from model import st_attention
from torchsummary import summary
from sklearn.metrics import auc, roc_curve
from tensorboardX import SummaryWriter
import argparse
from tqdm import tqdm
from time import time
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel

args = argparse.ArgumentParser()
args.add_argument('--name', type=str, default='paper_spec')
args.add_argument('--pad_size', type=int, default=19)
args.add_argument('--step_size', type=int, default=9)
args.add_argument('--model', type=str, default='st_attention')
args.add_argument('--lr', type=float, default=0.001)
args.add_argument('--opt', type=str, default='adam')
args.add_argument('--gpus', type=str, default='0,1,2,3')
args.add_argument('--epoch', type=int, default=50)
args.add_argument('--feature', type=str, default='mel')
args.add_argument('--noise_aug', action='store_true')
args.add_argument('--voice_aug', action='store_true')
args.add_argument('--aug', action='store_true')
args.add_argument('--resume', action='store_true')
args.add_argument('--skip', type=int, default=1)
args.add_argument('--decay', type=float, default=1/np.sqrt(2))
args.add_argument('--batch', type=int, default=512)
args.add_argument('--norm', type=str, default='paper', choices=['paper', 'timit'])
args.add_argument('--dataset', type=str, default='noisex')
config = args.parse_args()
os.environ['CUDA_VISIBLE_DEVICES'] = config.gpus
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
name = config.name
tensorboard_path = './tensorboard_log/'+name
model_save_path = './model_save/'+name
if not os.path.exists(tensorboard_path):
    os.makedirs(tensorboard_path)
writer = SummaryWriter(tensorboard_path)
if not os.path.exists(model_save_path):
    os.makedirs(model_save_path)

PATH = '/root/datasets/ai_challenge/ST_attention_dataset'
x = pickle.load(open(PATH+'/timit_noisex_x_mel.pickle', 'rb'))[:100]
y = pickle.load(open(PATH+'/timit_noisex_y_mel.pickle', 'rb'))[:100]
eval_y = pickle.load(open(PATH+'/libri_aurora_val_y_mel.pickle', 'rb'))[:100]
eval_x = pickle.load(open(PATH+'/libri_aurora_val_x_mel.pickle', 'rb'))[:100]
for i in range(len(x)):
    x[i] = x[i][:, :len(y[i])]
for i in range(len(eval_x)):
    eval_x[i] = eval_x[i][:, :len(eval_y[i])]
device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
perm = np.random.permutation(len(x))[:int(len(x) * 0.05)]
_x, _y, val_x, val_y = [],[],[],[]
for i in range(len(x)):
    if i in perm:
        val_x.append(x[i])
        val_y.append(y[i])
    else:
        _x.append(x[i])
        _y.append(y[i])
x = _x
y = _y

BATCH_SIZE = 512
EPOCHS = 200
LR = 0.01
EARLY_STOP_STEP = 10
regularization_weight = 0.1
train_times = 18
val_times = 1
eval_times = 3
transform = torchvision.transforms.Compose([transforms.ToTensor()])
trainloader = Dataloader_generator(x, y, transform, config=config,device=device, n_data_per_epoch=10000,divide=train_times, batch_size=BATCH_SIZE)
valloader = Dataloader_generator(val_x, val_y, transform, config=config, device=device, n_data_per_epoch=len(val_x), divide=val_times, batch_size=BATCH_SIZE)
evalloader = Dataloader_generator(eval_x, eval_y, transform, config=config, device=device, n_data_per_epoch=len(eval_x), divide=eval_times, batch_size=BATCH_SIZE)

model = st_attention(device=device)
model.to(device)
criterion = nn.BCELoss()
# optimizer = optim.SGD(model.parameters(),lr=LR,momentum=0.9)
optimizer = optim.Adam(model.parameters())
# lr_schedule = optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=config.decay)
lr_schedule = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=config.decay, patience=1, threshold=0.0001, threshold_mode='rel', cooldown=0, min_lr=0, eps=1e-08, verbose=True)
startepoch = 0
win = WindowUtils(config.pad_size, config.step_size, device)
min_loss = 1000000000000.0
if config.resume:
    if len(glob(model_save_path+'/*')) == 0:
        print('there is no checkpoint')
    else:
        resume = torch.load(sorted(glob(model_save_path+'/*'), key=lambda x: int(x.split('/')[-1].split('_')[0]),reverse=True)[0])
        model.load_state_dict(resume['model'])
        optimizer.load_state_dict(resume['optimizer'])
        startepoch = resume['epoch'] + 1
        min_loss = resume['min_loss']
        lr_schedule.load_state_dict(resume['lr_schedule'])
        
for epoch in range(startepoch,EPOCHS):
    trainloader.shuffle()
    start_time = time()
    running_loss, running_correct, running_auc = 0.0, 0.0, 0.0
    loader_len = 0
    for times in range(train_times):
        train_loader = next(iter(trainloader.next_loader(times)))
        model.train()
        # with tqdm(train_loader) as pbar:
        for idx, (data, label) in enumerate(train_loader):
            data = data.to(device)
            label = label.to(device)
            optimizer.zero_grad()
            pipe_score, multi_score, post_score = model(data)
            # _, preds = torch.max(post_loss, 1)
            preds = torch.round(post_score).detach()
            pipe_loss = criterion(pipe_score, label)
            multi_loss = criterion(multi_score, label)
            post_loss = criterion(post_score, label)
            loss = pipe_loss + multi_loss + regularization_weight * post_loss
            loss.backward()
            
            optimizer.step()
            running_loss += loss.item()
            # running_correct += torch.sum(preds == label.data)
                # fpr, tpr, thresholds = roc_curve(np.reshape(label.cpu().numpy(),(-1)), np.reshape(preds.cpu().detach().numpy(),(-1)))
                # running_auc += auc(fpr, tpr)
                # pbar.set_postfix(times=f'{times}/{train_times}',train_loss=f'loss: {running_loss / ((idx+1) + loader_len):0.4}', train_auc=f'auc: {running_auc / ((idx+1) + loader_len):0.4}', train_acc=f'acc: {running_correct / ((idx+1) + loader_len) / 7 / BATCH_SIZE:0.4}')
            loader_len += len(train_loader)
        train_loader = None
        torch.cuda.empty_cache()
    running_loss /= loader_len
    # running_correct /= loader_len * 7 * BATCH_SIZE
    # running_auc /= loader_len
    train_loader = None
    torch.cuda.empty_cache()
    model.eval()
    eval_loss, eval_correct, eval_auc = 0.0, 0.0, 0.0
    val_loss, val_correct, val_auc = 0.0, 0.0, 0.0
    with torch.no_grad():
        loader_len = 0
        for times in range(val_times):
            val_loader = next(iter(valloader.next_loader(times)))
            with tqdm(val_loader) as pbar:
                for idx, (data, label) in enumerate(pbar):
                    data = data.to(device)
                    label = label.to(device)
                    pipe_score, multi_score, post_score = model(data)
                    pipe_loss = criterion(pipe_score, label)
                    multi_loss = criterion(multi_score, label)
                    post_loss = criterion(post_score, label)
                    loss = pipe_loss + multi_loss + regularization_weight * post_loss
                    # _, preds = torch.max(post_loss, 1)
                    preds = torch.round(post_score).detach()
                    val_loss += loss.item()
                    val_correct += torch.sum(preds == label.data)
                    label_seq = win.windows_to_sequence(label.cpu(),config.pad_size,config.step_size)
                    preds_seq = win.windows_to_sequence(preds.cpu(),config.pad_size,config.step_size)
                    fpr, tpr, thresholds = roc_curve(label_seq.type(torch.int).numpy(), preds_seq.numpy(), pos_label=1)
                    val_auc += auc(fpr, tpr)
                    pbar.set_postfix(accuracy=f'val_loss: {val_loss / ((idx+1) + loader_len):0.4}, val_auc: {val_auc / ((idx+1) + loader_len):0.4}, val_acc: {val_correct / ((idx+1) + loader_len) / 7 / BATCH_SIZE:0.4}')
                loader_len += len(pbar)
            val_loader = None
            torch.cuda.empty_cache()
        val_loss /= loader_len
        val_correct /= loader_len * 7 * BATCH_SIZE
        val_auc /= loader_len

        loader_len = 0
        for times in range(eval_times):
            eval_loader = next(iter(evalloader.next_loader(times)))
            with tqdm(eval_loader) as pbar:
                for idx, (data, label) in enumerate(pbar):
                    data = data.to(device)
                    label = label.to(device)
                    pipe_score, multi_score, post_score = model(data)
                    pipe_loss = criterion(pipe_score, label)
                    multi_loss = criterion(multi_score, label)
                    post_loss = criterion(post_score, label)
                    loss = pipe_loss + multi_loss + regularization_weight * post_loss
                    # _, preds = torch.max(post_loss, 1)
                    preds = torch.round(post_score).clone()
                    eval_loss += loss.item()
                    eval_correct += torch.sum(preds == label.data).cpu()
                    label_seq = win.windows_to_sequence(label.cpu(),config.pad_size,config.step_size)
                    preds_seq = win.windows_to_sequence(preds.cpu(),config.pad_size,config.step_size)
                    fpr, tpr, thresholds = roc_curve(label_seq.type(torch.int).numpy(), preds_seq.numpy(), pos_label=1)
                    _eval_auc = auc(fpr, tpr)
                    eval_auc += _eval_auc
                    pbar.set_postfix(accuracy=f'eval_loss: {eval_loss / ((idx+1) + loader_len):0.4}, eval_auc: {eval_auc / ((idx+1) + loader_len):0.4}, eval_acc: {eval_correct / ((idx+1) + loader_len) / 7 / BATCH_SIZE:0.4}')
            
                loader_len += len(pbar)
            eval_loader = None
            torch.cuda.empty_cache()
        eval_loss /= loader_len
        eval_correct /= loader_len * 7 * BATCH_SIZE
        eval_auc /= loader_len
    writer.add_scalar('loss/train_loss',running_loss, epoch)
    # writer.add_scalar('acc/train_acc',running_correct, epoch)
    # writer.add_scalar('auc/train_auc',running_auc, epoch)
    writer.add_scalar('loss/val_loss',val_loss, epoch)
    writer.add_scalar('acc/val_acc',val_correct, epoch)
    writer.add_scalar('auc/val_auc',val_auc, epoch)
    writer.add_scalar('loss/eval_loss',eval_loss, epoch)
    writer.add_scalar('acc/eval_acc',eval_correct, epoch)
    writer.add_scalar('auc/eval_auc',eval_auc, epoch)
    print(f'epoch: {epoch} loss: {running_loss:0.4}, val_loss: {val_loss:0.4}, val_acc: {val_correct:0.4}, val_auc: {val_auc:0.4}, eval_loss: {eval_loss:0.4}, eval_acc: {eval_correct:0.4}, eval_auc: {eval_auc:0.4}, time: {time() - start_time:0.4}')
    if np.isnan(eval_auc) or np.isnan(eval_correct) or np.isnan(eval_loss):
        print(f'Nan is detected, eval_auc: {eval_auc:0.4}, eval_acc: {eval_correct:0.4}, eval_loss{eval_loss:0.4}')
        break
    torch.save({
        'model':model.state_dict(),
        'optimizer':optimizer.state_dict(),
        'epoch':epoch,
        'lr_schedule':lr_schedule.state_dict(),
        'min_loss':min_loss
        }, model_save_path + f'/{epoch}_auc{eval_auc:0.4}.pt')
    
    lr_schedule.step(val_loss)
    torch.cuda.empty_cache()
    if val_loss < min_loss:
        epochs_no_improve = 0
        # min_loss = val_loss
    else:
        epochs_no_improve += 1
    if epoch > 5 and epochs_no_improve == EARLY_STOP_STEP:
        print('Early stopping!' )
        break
    else:
        continue