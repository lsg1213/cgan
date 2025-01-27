import argparse,pdb
import numpy as np
def get_arg(known=[]):
    args = argparse.ArgumentParser()
    args.add_argument('--lr', type=float, default=0.001)
    args.add_argument('--gpus', type=str, default='0')
    args.add_argument('--name', type=str, default='')
    args.add_argument('--epoch', type=int, default=200)
    args.add_argument('--decay', type=float, default=1/np.sqrt(2))
    args.add_argument('--batch', type=int, default=128)
    args.add_argument('--len', type=int, default=200)
    args.add_argument('--b', type=int, default=200)
    args.add_argument('--opt', type=str, default='adam')
    args.add_argument('--model', type=str, default='CombineAutoencoder', choices=['skip_model', 'CNN','CombineAutoencoder', 'ResNext', 'efficientnet'])
    args.add_argument('--resume', action='store_true')
    args.add_argument('--relu', action='store_true')
    args.add_argument('--future', type=bool, default=True)
    args.add_argument('--diff', type=str, default='nodiff', choices=['nodiff', 'diff', 'double'])
    args.add_argument('--subtract', type=bool, default=True)
    args.add_argument('--sr', type=int, default=8192)
    args.add_argument('--latency', type=int, default=24, help='latency frame numuber between accel and data')
    args.add_argument('--feature', type=str, default='wav', choices=['wav', 'mel', 'stft'])
    args.add_argument('--nmels', type=int, default=80)
    args.add_argument('--nfft', type=int, default=1024)
    args.add_argument('--loss_weight', type=float, default=0.1)
    args.add_argument('--split_number', type=int, default=-1)
    args.add_argument('--class_num', type=int, default=200)
    args.add_argument('--loss', type=str, default='l1', choices=['custom', 'l1', 'l2'])
    args.add_argument('--smoo', type=int, default=50)
    args.add_argument('--data_per_epoch', type=int, default=4000)
    args.add_argument('--st2st', action='store_true')
    args.add_argument('--filter', action='store_true')
    args.add_argument('--range', type=str, default='90~100')
    args.add_argument('--win_len', type=int, default=0)
    args.add_argument('--hop_len', type=int, default=0)
    args.add_argument('--highpass', type=int, default=20)
    args.add_argument('--norm', type=bool, default=False)
    args.add_argument('--snd_max', type=float, default=7.5)
    args.add_argument('--snd_min', type=float, default=-7.5)
    args.add_argument('--acc_max', type=float, default=0.5)
    args.add_argument('--acc_min', type=float, default=-0.5)
    # resnext argument
    args.add_argument('--depth', type=int, default=29, help='Model depth.')
    args.add_argument('--nlabels', type=int, default=400, help='')
    args.add_argument('--cardinality', type=int, default=8, help='Model cardinality (group).')
    args.add_argument('--base_width', type=int, default=64, help='Number of channels in each group.')
    args.add_argument('--widen_factor', type=int, default=4, help='Widen factor. 4 -> 64, 8 -> 128, ...')
    


    arg = args.parse_known_args(known)[0]
    if arg.split_number == -1:
        arg.split_number = arg.len // 2
    if arg.filter and arg.nfft > arg.len:
        arg.nfft = arg.len
    if arg.win_len == 0:
        arg.win_len = arg.nfft
    if arg.hop_len == 0:
        arg.hop_len = arg.nfft // 2
    
    return arg


if __name__ == "__main__":
    import sys, pdb
    pdb.set_trace()