# Contains routines for labels creation, features extraction and normalization
#


import os, pdb, scipy.io
import numpy as np
import scipy.io.wavfile as wav
import utils
from sklearn import preprocessing
import joblib
from IPython import embed
import matplotlib.pyplot as plot
from concurrent.futures import ThreadPoolExecutor
plot.switch_backend('agg')
from glob import glob

class FeatureClass:
    def __init__(self, nfft=1024, wav_extra_name='', desc_extra_name='', datasettype='train', config=None):
        self.config = config
        self.datasettype = datasettype
        # Output directories
        self._label_dir = None
        self._feat_dir = None
        self._feat_dir_norm = None

        # Local parameters
        self._mode = None
        self._nfft = nfft
        self._win_len = self._nfft
        self._hop_len = self._nfft//2
        self._eps = np.spacing(np.float(1e-16))

        self._nb_channels = 2

        self._fs = 16000
        self._frame_res = self._fs / float(self._hop_len)
        self._hop_len_s = self._nfft/2.0/self._fs
        self._nb_frames_1s = int(1 / self._hop_len_s)
        self._fade_win_size = 0.01 * self._fs

        self._resolution = 20
        self._azi_list = range(0, 220, self._resolution)
        self._length = len(self._azi_list)
        self._weakness = None
        self._unique_classes = [0,20,40,60,80,100,120,140,160,180,-1]

        # For regression task only
        self._default_azi = 90

        if self._default_azi in self._azi_list:
            print('ERROR: chosen default_azi value {} should not exist in azi_list'.format(self._default_azi))
            exit()
        self._second = config.s
        self._audio_max_len_samples = self._second * self._fs  # TODO: Fix the audio synthesis code to always generate 30s of
        # audio. Currently it generates audio till the last active sound event, which is not always 30s long. This is a
        # quick fix to overcome that. We need this because, for processing and training we need the length of features
        # to be fixed.

        self._max_frames = int(np.ceil((self._audio_max_len_samples - self._win_len) / float(self._hop_len)))
        
        self._base_folder = os.path.join(f'/root/datasets/ai_challenge/seldnet/{self.config.dataset}/{self._second}')
        utils.create_folder(self._base_folder)
        # Input directories
        if datasettype == 'train':
            self.f_dir = os.path.join(self._base_folder, 'train/flabel')
            self._aud_dir = os.path.join(self._base_folder, 'train')
            self._desc_dir = os.path.join(self._base_folder, 'train')
            
        elif datasettype == 'validation':
            self.f_dir = os.path.join(self._base_folder, 'validation/flabel')
            self._aud_dir = os.path.join(self._base_folder, 'validation')
            self._desc_dir = os.path.join(self._base_folder, 'validation')

        elif datasettype == 'test':
            self.f_dir = os.path.join(self._base_folder, 'test/flabel')
            self._aud_dir = os.path.join(self._base_folder, 'test')
            self._desc_dir = os.path.join(self._base_folder, 'test')

        utils.create_folder(self.f_dir)
        
    def _load_audio(self, audio_path):
        fs, audio = scipy.io.wavfile.read(audio_path)
        
        wa = audio[:, :self._nb_channels] / 32768.0 + self._eps
        if wa.shape[0] < self._audio_max_len_samples:
            zero_pad = np.zeros((self._audio_max_len_samples - wa.shape[0], wa.shape[1]))
            wa = np.vstack((wa, zero_pad))
        elif wa.shape[0] > self._audio_max_len_samples:
            wa = wa[:self._audio_max_len_samples, :]
        return wa, fs

    # INPUT FEATURES
    @staticmethod
    def _next_greater_power_of_2(x):
        return 2 ** (x - 1).bit_length()

    def _spectrogram(self, audio_input):
        _nb_ch = audio_input.shape[1]
        hann_win = np.repeat(np.hanning(self._win_len)[np.newaxis].T, _nb_ch, 1)
        nb_bins = self._nfft // 2
        spectra = np.zeros((self._max_frames, nb_bins, _nb_ch), dtype=complex)
        for ind in range(self._max_frames):
            start_ind = ind * self._hop_len
            aud_frame = audio_input[start_ind + np.arange(0, self._win_len), :] * hann_win
            spectra[ind] = np.fft.fft(aud_frame, n=self._nfft, axis=0, norm='ortho')[:nb_bins, :]
        return spectra

    def frametowindow(self, flabel):
        # flabel (alllabel,)
        window = np.zeros((self._max_frames,), dtype=np.int8)
        flabel = flabel.astype(np.int8)
        for ind in range(self._max_frames):
            start_ind = ind * self._hop_len
            frames = flabel[start_ind + np.arange(0, self._win_len)]
            la = np.unique(frames)
            window[ind] = 10 if len(la) == 1 else sorted(la)[0]
        return window

    def label_padding(self, labels):
        if len(labels) < self._audio_max_len_samples:
            zero_pad = np.ones((self._audio_max_len_samples - len(labels))) * 10
            labels = np.concatenate((labels, zero_pad))
        elif len(labels) > self._audio_max_len_samples:
            labels = labels[:self._audio_max_len_samples]
        return labels

    def _extract_spectrogram_for_file(self, audio_filename):
        audio_in, fs = self._load_audio(os.path.join(self._aud_dir, audio_filename))
        

        # with ThreadPoolExecutor() as pool:
        #     flabel = list(pool.map(self.label_padding, flabel))
        audio_spec = self._spectrogram(audio_in)
        
        # with ThreadPoolExecutor(max_workers=80) as pool:
        #     flabel_spec = np.array(list(map(self.frametowindow, flabel)))
        
        joblib.dump(audio_spec.reshape(self._max_frames, -1), open(os.path.join(self._feat_dir, audio_filename.split('/')[-1].split('.')[0]+'.joblib'), 'wb'))
        # joblib.dump(flabel_spec, open(os.path.join('/'.join(self.f_dir.split('/')[:-1]), os.path.basename(self.f_dir).split('frame')[0] + 'window.joblib'), 'wb'))

    def get_list_index(self, azi, ele):
        azi = (azi - self._azi_list[0]) // 10
        ele = (ele - self._ele_list[0]) // 10
        return azi * self._height + ele

    def _get_matrix_index(self, ind):
        azi, ele = ind // self._height, ind % self._height
        azi = (azi * 10 + self._azi_list[0])
        ele = (ele * 10 + self._ele_list[0])
        return azi, ele

    def get_vector_index(self, ind):
        azi = (ind * 10 + self._azi_list[0])
        return azi

    @staticmethod
    def scaled_cross_product(a, b):
        ab = np.dot(a, b)
        if ab > 1 or ab < -1:
            return [999]

        acos_ab = np.arccos(ab)
        x = np.cross(a, b)
        if acos_ab == np.pi or acos_ab == 0 or sum(x) == 0:
            return [999]
        else:
            return x/np.sqrt(np.sum(x**2))

    def get_trajectory(self, event_length_s, _start_xyz, _rot_vec, _random_ang_vel):
        frames_per_sec = self._fs / self._fade_win_size
        ang_vel_per_win = _random_ang_vel / frames_per_sec
        nb_frames = int(np.ceil(event_length_s * frames_per_sec))
        xyz_array = np.zeros((nb_frames, 3))
        for frame in range(nb_frames):
            _R = self.rotate_matrix_vec_ang(_rot_vec, frame * ang_vel_per_win)
            xyz_array[frame, :] = np.dot(_start_xyz, _R.T)
        return xyz_array


    @staticmethod
    def rotate_matrix_vec_ang(_rot_vec, theta):
        u_x_u = np.array(
            [
                [_rot_vec[0] ** 2, _rot_vec[0] * _rot_vec[1], _rot_vec[0] * _rot_vec[2]],
                [_rot_vec[1] * _rot_vec[0], _rot_vec[1] ** 2, _rot_vec[1] * _rot_vec[2]],
                [_rot_vec[2] * _rot_vec[0], _rot_vec[2] * _rot_vec[1], _rot_vec[2] ** 2]
            ]
        )

        u_x = np.array(
            [
                [0, -_rot_vec[2], _rot_vec[1]],
                [_rot_vec[2], 0, -_rot_vec[0]],
                [-_rot_vec[1], _rot_vec[0], 0]
            ]
        )
        return np.eye(3) * np.cos(theta) + np.sin(theta) * u_x + (1 - np.cos(theta)) * u_x_u

    @staticmethod
    def sph2cart(az, el, r):
        """
        Converts spherical coordinates given by azimuthal, elevation and radius to cartesian coordinates of x, y and z

        :param az: azimuth angle
        :param el: elevation angle
        :param r: radius
        :return: cartesian coordinate
        """
        rcos_theta = r * np.cos(el)
        x = rcos_theta * np.cos(az)
        y = rcos_theta * np.sin(az)
        z = r * np.sin(el)
        return x, y, z

    @staticmethod
    def cart2sph(x, y, z):
        XsqPlusYsq = x ** 2 + y ** 2
        r = np.sqrt(XsqPlusYsq + z ** 2)  # r
        elev = np.arctan2(z, np.sqrt(XsqPlusYsq))  # theta
        az = np.arctan2(y, x)  # phi
        return az, elev, r

    @staticmethod
    def wrapToPi(rad_list):
        xwrap = np.remainder(rad_list, 2 * np.pi)
        mask = np.abs(xwrap) > np.pi
        xwrap[mask] -= 2 * np.pi * np.sign(xwrap[mask])
        return xwrap

    def wrapTo180(self, deg_list):
        rad_list = deg_list * np.pi / 180.
        rad_list = self.wrapToPi(rad_list)
        deg_list = rad_list * 180 / np.pi
        return deg_list


    # ------------------------------- EXTRACT FEATURE AND PREPROCESS IT -------------------------------
    def extract_all_feature(self, extra=''):
        # setting up folders
        self._feat_dir = self.get_unnormalized_feat_dir(extra)
        utils.create_folder(self._feat_dir)
        
        # extraction starts
        print('Extracting spectrogram:')
        print('\t\taud_dir {}\n\t\tdesc_dir {}\n\t\tfeat_dir {}'.format(
            self._aud_dir, self._desc_dir, self._feat_dir))
        for aud_dir in os.listdir(self._aud_dir):
            if '.wav' in aud_dir:
                self._extract_spectrogram_for_file(aud_dir)

    def preprocess_features(self, extra=''):
        # Setting up folders and filenames
        self._feat_dir = self.get_unnormalized_feat_dir(extra)
        self._feat_dir_norm = self.get_normalized_feat_dir(extra)
        
        utils.create_folder(self._feat_dir_norm)
        normalized_features_wts_file = self.get_normalized_wts_file(extra)

        # pre-processing starts
        print('Estimating weights for normalizing feature files:')
        print('\t\tfeat_dir {}'.format(self._feat_dir))

        spec_scaler = preprocessing.StandardScaler()
        train_cnt = 0
        for file_cnt, file_name in enumerate(os.listdir(self._feat_dir)):
            feat_file = joblib.load(os.path.join(self._feat_dir, file_name))
            spec_scaler.partial_fit(np.concatenate((np.abs(feat_file), np.angle(feat_file)), axis=1))
            del feat_file
        joblib.dump(
            spec_scaler,
            normalized_features_wts_file
        )

        print('Normalizing feature files:')
        # spec_scaler = joblib.load(normalized_features_wts_file) #load weights again using this command
        for file_cnt, file_name in enumerate(os.listdir(self._feat_dir)):
            print(file_cnt, file_name)
            feat_file = joblib.load(os.path.join(self._feat_dir, file_name))
            feat_file = spec_scaler.transform(np.concatenate((np.abs(feat_file), np.angle(feat_file)), axis=1))
            joblib.dump(
                feat_file,
                open(os.path.join(self._feat_dir_norm, file_name), 'wb')
            )
            del feat_file
        print('normalized files written to {} folder and the scaler to {}'.format(
            self._feat_dir_norm, normalized_features_wts_file))

    def normalize_features(self, extraname=''):
        # Setting up folders and filenames
        self._feat_dir = self.get_unnormalized_feat_dir(extraname)
        self._feat_dir_norm = self.get_normalized_feat_dir(extraname)
        utils.create_folder(self._feat_dir_norm)
        normalized_features_wts_file = self.get_normalized_wts_file()

        # pre-processing starts
        print('Estimating weights for normalizing feature files:')
        print('\t\tfeat_dir {}'.format(self._feat_dir))

        spec_scaler = joblib.load(normalized_features_wts_file)
        print('Normalizing feature files:')
        # spec_scaler = joblib.load(normalized_features_wts_file) #load weights again using this command
        for file_cnt, file_name in enumerate(os.listdir(self._feat_dir)):
            print(file_cnt, file_name)
            feat_file = np.load(os.path.join(self._feat_dir, file_name))
            feat_file = spec_scaler.transform(np.concatenate((np.abs(feat_file), np.angle(feat_file)), axis=1))
            np.save(
                os.path.join(self._feat_dir_norm, file_name),
                feat_file
            )
            del feat_file
        print('normalized files written to {} folder and the scaler to {}'.format(
            self._feat_dir_norm, normalized_features_wts_file))

    # ------------------------------- EXTRACT LABELS AND PREPROCESS IT -------------------------------
    def extract_all_labels(self, extra=''):
        self._label_dir = self.get_label_dir(extra)
        if self.datasettype == 'train':
            self._label_dir = os.path.join(self._label_dir, 'train')
        elif self.datasettype == 'validation':
            self._label_dir = os.path.join(self._label_dir, 'validation')
        elif self.datasettype == 'test':
            self._label_dir = os.path.join(self._label_dir, 'test')

        print('Extracting spectrogram and labels:')
        print('\t\taud_dir {}\n\t\tdesc_dir {}\n\t\tlabel_dir {}'.format(
            self._aud_dir, self._desc_dir, self._label_dir))
        
        for i in sorted(glob(self._desc_dir+'/*_label.joblib')):
            label = joblib.load(open(i, 'rb'))
            if label.shape[0] == self._nb_channels:
                label = label.transpose(-1,-2)
            labels = np.zeros((self._max_frames, self._nfft // 2), dtype=label.dtype)
            for ind in range(self._max_frames):
                start_ind = ind * self._hop_len
                labels[ind] = label[start_ind + np.arange(0, self._nfft // 2)]
            
            joblib.dump(labels.reshape(self._max_frames, -1), open(os.path.join(self.f_dir, os.path.basename(i)), 'wb'))
            del label
            

            

    # ------------------------------- Misc public functions -------------------------------
    def get_classes(self):
        return self._unique_classes

    def get_normalized_feat_dir(self, extra=''):
        if self.datasettype == 'train':
            return os.path.join(
                self._base_folder + '/train',
                'nfft{}{}_norm'.format(self._nfft, extra)
            )
        elif self.datasettype == 'validation':
            return os.path.join(
                self._base_folder + '/validation',
                'nfft{}{}_norm'.format(self._nfft, extra)
            )
        elif self.datasettype == 'test':
            return os.path.join(
                self._base_folder + '/test',
                'nfft{}{}_norm'.format(self._nfft, extra)
            )

    def get_unnormalized_feat_dir(self, extra=''):
        if self.datasettype == 'train':
            return os.path.join(
                self._base_folder + '/train',
                'nfft{}{}'.format(self._nfft, extra)
            )

        elif self.datasettype == 'validation':
            return os.path.join(
                self._base_folder + '/validation',
                'nfft{}{}'.format(self._nfft, extra)
            )
        elif self.datasettype == 'test':
            return os.path.join(
                self._base_folder + '/test',
                'nfft{}{}'.format(self._nfft, extra)
            )

    def get_label_dir(self, extra=''):
        return '/'.join(self._desc_dir.split('/')[:-1])

    def get_normalized_wts_file(self, extra=''):
        return os.path.join(
            self._base_folder,
            'nfft{}{}_wts'.format(self._nfft, extra)
        )

    def get_default_azi_ele_regr(self):
        return self._default_azi

    def get_nb_channels(self):
        return self._nb_channels

    def nb_frames_1s(self):
        return self._nb_frames_1s

if __name__ == "__main__":
    import librosa, pickle
    import concurrent.futures as fu
    import scipy.io
    def loading(path):
        data, sr = librosa.load(path, sr=None, mono=False)
        data = librosa.resample(data, sr, 16000)
        return data
    
    base_folder = os.path.join('/root/datasets/ai_challenge/interspeech20/train')
    save_path = '/root/datasets/ai_challenge/interspeech20/seld'

    testx = sorted(glob('/root/datasets/ai_challenge/t3_audio/*.wav'))
    with fu.ThreadPoolExecutor() as pool:
        x = list(pool.map(loading, testx))
    joblib.dump(x, open(os.path.join(save_path, 'test_x.joblib'), 'wb'))


    x_dir = sorted(glob(os.path.join(base_folder, '*.wav')))
    y = scipy.io.loadmat(os.path.join(base_folder, 'angle.mat'))
    joblib.dump(y['phi'][0], open(os.path.join(save_path, 'train_y.joblib'), 'wb'))

    with fu.ThreadPoolExecutor() as pool:
        x = list(pool.map(loading, x_dir))
    joblib.dump(x, open(os.path.join(save_path, 'train_x.joblib'), 'wb'))
    
    testy = pickle.load(open('/root/datasets/ai_challenge/icassp/final_y.pickle', 'rb'))
    joblib.dump(testy, open(os.path.join(save_path, 'test_y.joblib'), 'wb'))