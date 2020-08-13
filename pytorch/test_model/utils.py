import torch, pdb
from torch.utils.data import DataLoader, Dataset
import numpy as np
import torch.nn.functional as F

def dataSplit(data, takebeforetime, data_length=40):
    device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')
    # data shape list(25, np(987136, 12)), accel, 주의: 샘플별로 안 섞이게 하기
    # 이걸 자르기, (index, window, channel)
    # data_length = int(hp.audio.sr * hp.audio.win_length / 1000000)
    # import pdb; pdb.set_trace()
    if takebeforetime != 0:
        data = [np.concatenate([np.zeros((takebeforetime, i.shape[1]),dtype='float'), i]) for i in data]
    splited_data = torch.cat([torch.cat([torch.from_numpy(_data[idx-takebeforetime:idx+data_length][np.newaxis, ...]) for idx in range(takebeforetime, len(_data) // data_length )]) for _data in data])
    
    return splited_data.cpu()

class makeDataset(Dataset):
    def __init__(self, accel, sound, train=True):
        self.accel = accel
        self.sound = sound
        if train:
            perm = torch.randperm(len(self.accel))
            self.accel = self.accel[perm]
            self.sound = self.sound[perm]
    
    def __len__(self):
        return len(self.accel)

    def __getitem__(self, idx):
        return self.accel[idx], self.sound[idx]

def Shift(y_buffer, k_idx, value):
    y_buffer[1:, k_idx] = y_buffer[:-1, k_idx]
    y_buffer[0, k_idx] = value
    return y_buffer
Ls = 128
K = M = 8
def Conv_S(signal, S_data, device='cpu'):
    #Process S filter to waveform data
    #the shape of signal should be (batch, time, 8)
    batch_size = signal.size(0)
    time_len = signal.size(1)
    y_pred = torch.zeros((batch_size, time_len, M), device=device)
    S_filter = S_data.type(torch.float) #(Ls, K, M)
    Y_buffer = torch.zeros((Ls, K), device=device)
    for batch in range(batch_size):
        for n in range(time_len):
            for k in range(K):
                for m in range(M):
                    y_pred[batch, n, m] += torch.dot(Y_buffer[:, k], S_filter[:, k, m])
                    Y_buffer = Shift(Y_buffer, k, signal[batch, n, k])
        
    return y_pred

def padding(signal, device):
    _pad = torch.zeros((signal.size(0), Ls - 1, signal.size(2))).to(device)
    return torch.cat([_pad, signal],1)
    
def conv_with_S(signal, S_data, device=torch.device('cpu')):
    signal = padding(signal, device)
    if signal.size(1) != K:
        signal = signal.transpose(1,2)
    if S_data.size(0) == Ls:
        S_data = S_data.transpose(0,2)
    out = F.conv1d(signal, S_data)

    return out.transpose(1,2)