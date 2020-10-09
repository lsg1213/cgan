import torch, torchaudio, pdb, librosa
from torch.utils.data import DataLoader, Dataset
import numpy as np
import torch.nn.functional as F
from scipy.io.wavfile import write
import concurrent.futures as fu

def data_spread(data, data_length, config):
    '''
    (number of file, frames, channel) => (all frames, channel)
    and cut wave frames by data_length
    '''
    if type(data) == list:
        res = torch.cat([torch.tensor(i) for i in data])
    
    return res

def inverse_mel(data, sr=8192, n_mels=160):
    # data = (batch, )
    # data = 
    pass
    
class makeDataset(Dataset):
    def __init__(self, accel, sound, config, train=True):
        self.config = config
        self.takebeforetime = config.b
        self.data_length = config.len

        if self.takebeforetime % self.data_length != 0:
            raise ValueError(f'takebeforetime must be the multiple of data_length, {takebeforetime}')
        
        self.accel = data_spread(accel, self.data_length, config)
        self.sound = data_spread(sound, self.data_length, config)
        self.perm = torch.arange(len(self.accel) - self.config.latency - self.config.b - 2 * self.config.len if self.config.future else len(self.accel))
        if train:
            self.shuffle()
        self.len = len(self.accel) - config.b - config.len - config.latency
        if self.config.future:
            self.len -= self.config.len
    
    def shuffle(self):
        self.perm = torch.arange(len(self.accel) - self.config.latency - self.config.b - 2 * self.config.len if self.config.future else len(self.accel))

    def __len__(self):
        return self.len

    def __getitem__(self, idx):
        idx = self.perm[idx]
        index = idx + self.config.latency
        accel = self.accel[idx:idx + self.config.b + self.config.len]
        if self.config.future:
            sound = self.sound[index + self.config.len:index + 2 * self.config.len]
        else:
            sound = self.sound[index:index + self.config.len]

        if self.config.feature == 'wav':
            return accel.transpose(0,1), sound
        elif self.config.feature == 'mel':
            # (frames, 12)
            # return wavtomel(accel, self.config).transpose(0,1), wavtomel(sound, self.config).transpose(0,1)
            return wavtomel(accel, self.config).transpose(0,1), sound
        elif self.config.feature == 'mfcc':
            # (frames, 12)
            pass

def padding(signal, Ls):
    _pad = torch.zeros((signal.size(0), Ls, signal.size(2)), device=signal.device, dtype=signal.dtype)
    return torch.cat([_pad, signal],1)

def wavtomel(wav, config):
    # (frames, 12)
    def _wavtomel(_wav):
        # (frames) to (mels, frames)
        return librosa.feature.melspectrogram(_wav, sr=config.sr, n_mels=config.nmels, n_fft=config.nfft, hop_length=config.nfft // 2 if config.nfft // 2 != 0 else 1, win_length=config.nfft)
    
    if len(wav.shape) == 2:
        with fu.ThreadPoolExecutor() as pool:
            data = torch.tensor(list(pool.map(_wavtomel, wav.transpose(0,1).numpy())), dtype=wav.dtype, device=wav.device)

    return data    

# def meltowav(mel, config):
#     # mel shape = (batch, nmels, 8, frames)
#     if len(mel.shape) == 4:
#         mel = mel.transpose(2,3)  # (batch, nmels, frames, 8)
#     else:
#         raise ValueError(f'mel dimension must be 4, now {len(mel.shape)}')
    
#     def _meltowav(mel):
#         # (nmels, frames)
#         return librosa.feature.inverse.mel_to_audio(mel, sr=config.sr, n_fft=config.nfft, hop_length=config.nfft // 2, win_length=config.nfft)
#     wav = []
#     for idx, data in enumerate(mel):
#         #(nmels, frames, 8)
#         data = data.permute((2,0,1)) #(8, nmels, frames)
#         with fu.ThreadPoolExecutor() as pool:
#             _data = list(pool.map(_meltowav, data.numpy()))
#         wav.append(torch.tensor(_data, dtype=data.dtype, device=data.device))
#     pdb.set_trace()
#     return torch.cat(wav)

def conv_with_S(signal, S_data, config, device=torch.device('cpu')):
    # S_data(Ls, K, M)
    if config.ema:
        signal = ema(signal, n=2)
    S_data = torch.tensor(S_data.transpose(0,1).cpu().numpy()[:,::-1,:].copy(),device=signal.device)
    Ls = S_data.size(1)
    K = S_data.size(-1)
    signal = padding(signal, Ls)
    if signal.size(1) != K:
        signal = signal.transpose(1,2)
    
    out = F.conv1d(signal, S_data.permute([2,0,1]).type(signal.dtype)).transpose(1,2)[:,:-1,:]
    
    return out 

import numpy as np
import scipy
from scipy.signal import welch, hann
import matplotlib.pyplot as plt

# FILTERA Generates an A-weighting filter.
#    FILTERA Uses a closed-form expression to generate
#    an A-weighting filter for arbitary frequencies.
#
# Author: Douglas R. Lanman, 11/21/05

# Define filter coefficients.
# See: http://www.beis.de/Elektronik/AudioMeasure/
# WeightingFilters.html#A-Weighting
def filter_A(F):
    c1 = 3.5041384e16
    c2 = 20.598997 ** 2
    c3 = 107.65265 ** 2
    c4 = 737.86223 ** 2
    c5 = 12194.217 ** 2

    f = F
    arr = np.array(list(map(lambda x : 1e-17 if x == 0 else x, f)))

    num = np.sqrt(c1 * (arr ** 8))
    den = (f ** 2 + c2) * np.sqrt((f ** 2 + c3) * (f**2 + c4)) * (f ** 2 + c5)
    A = num / den
    return A

def write_wav(data, sr=8192, name='test_gen'):
    data = data.type(torch.float32).numpy()
    data = data - np.min(data)
    data /= np.max(data)
    write(name+'.wav', sr, data)
    return data

def dBA_metric(y, gt, plot=True):
    """
    |args|
    :y: generated sound data, it's shape should be (time, 8)
    :gt: ground truth data, it's shape should be (time, 8)
    :plot: if True, plot graph of each channels
    """
    d = gt
    e = gt - y
    Tn = y.shape[0]
    K = 8
    M = 8
    """Post processing : performance metric and plots"""
    p_ref = 20e-6
    fs = 2000
    Nfft = fs
    noverlap = Nfft / 2
    t = (np.arange(Tn) / fs)[np.newaxis, :]
    win = hann(fs, False)
    #autopower calculation
    D = np.zeros((int(Nfft/2 + 1), M))
    E = np.zeros((int(Nfft/2 + 1), M))
    for m in range(M):
        F, D[:,m] = welch(d[:, m], fs, window=win, noverlap=noverlap, nfft=Nfft, return_onesided=True, detrend=False)
        F, E[:,m] = welch(e[:, m], fs, window=win, noverlap=noverlap, nfft=Nfft, return_onesided=True, detrend=False)
    
    A = filter_A(F)
    AA = np.concatenate([[A]] * M, axis=0).transpose(1,0)
    D_A = D * AA ** 2 / p_ref ** 2
    E_A = E * AA ** 2 / p_ref ** 2
    
    # perfomance metric calculation
    D_A_dBA_Sum = np.zeros((1,M))
    E_A_dBA_Sum = np.zeros((1,M))
    freq_range = np.arange(500)
    result = []
    for m in range(M):
        D_A_dBA_Sum[0, m] = 10 * np.log10(np.sum(D_A[freq_range, m]))
        E_A_dBA_Sum[0, m] = 10 * np.log10(np.sum(E_A[freq_range, m]))
        result.append(D_A_dBA_Sum[0,m] - E_A_dBA_Sum[0,m])
    result.append(np.array(np.mean(result)))
    avg_result = np.mean(result)
    
    if plot:
        for m in range(M):
            plt.subplot(2, 4, m+1)
            da = D_A[:,m]
            ea = E_A[:,m]
            plt.plot(F, 10 * np.log10(da), color="red", label=f'D{D_A_dBA_Sum[0, m]:.2f}dBA')
            plt.plot(F, 10 * np.log10(ea), color="blue", label=f'E{E_A_dBA_Sum[0, m]:.2f}dBA')
            plt.legend()
            plt.ylim((10, 60))
            plt.xlim((20,1000))
            plt.xlabel('Frequency(Hz)')
            plt.ylabel('Level(dBA)')
        plt.tight_layout()
        plt.show()
    
    return avg_result

def ema(data, n=2):
    '''
    exponential mov
    '''
    smoothing_factor = 2. / (n + 1)
    #get n sma first and calculate the next n period ema
    ema = torch.zeros_like(data, dtype=data.dtype, device=data.device)
    ema[:n] = torch.mean(data[:n])

    #EMA(current) = ( (Price(current) - EMA(prev) ) x Multiplier) + EMA(prev)
    for i,j in enumerate(data[n:]):
        ema[i] = ((j - ema[i-1]) * smoothing_factor) + ema[i-1]

    return ema