#
# The SELDnet architecture
#

# from keras.layers import Bidirectional, Conv2D, MaxPooling2D, Input, MaxPooling3D, Conv3D
# from keras.layers.core import Dense, Activation, Dropout, Reshape, Permute
# from keras.layers.recurrent import GRU
# from keras.layers.normalization import BatchNormalization
# from keras.models import Model
# from keras.layers.wrappers import TimeDistributed
# from keras.optimizers import Adam
# import keras
# keras.backend.set_image_data_format('channels_first')
from tensorflow.keras.layers import Bidirectional, Conv2D, MaxPooling2D, Input, MaxPool2D, Conv3D, Dense, Activation, Dropout, Reshape, Permute, GRU, BatchNormalization, TimeDistributed, Flatten
from tensorflow.keras import Model
from tensorflow.keras.optimizers import Adam
import pdb

def get_model(data_in, data_out, dropout_rate, nb_cnn2d_filt, pool_size,
                                rnn_size, fnn_size, weights):
    # model definition
    spec_start = Input(shape=(data_in[-3], data_in[-2], data_in[-1]))
    spec_cnn = spec_start
    for i, convCnt in enumerate(pool_size):
        spec_cnn = Conv2D(filters=nb_cnn2d_filt, kernel_size=(3, 3), padding='same')(spec_cnn)
        spec_cnn = BatchNormalization()(spec_cnn)
        spec_cnn = Activation('relu')(spec_cnn)
        spec_cnn = MaxPooling2D(pool_size=(1, pool_size[i]))(spec_cnn)
        spec_cnn = Dropout(dropout_rate)(spec_cnn)
    spec_cnn = Permute((2, 1, 3))(spec_cnn)
    
    # spec_rnn = Reshape((data_in[-2], -1))(spec_cnn)
    spec_rnn = Reshape((1, -1))(spec_cnn)
    for nb_rnn_filt in rnn_size:
        spec_rnn = Bidirectional(
            GRU(nb_rnn_filt, activation='tanh', dropout=dropout_rate, recurrent_dropout=dropout_rate,
                return_sequences=True),
            merge_mode='mul'
        )(spec_rnn)

    doa = spec_rnn
    for nb_fnn_filt in fnn_size:
        # doa = TimeDistributed(Dense(nb_fnn_filt))(doa)
        doa = Dense(nb_fnn_filt)(doa)
        doa = Dropout(dropout_rate)(doa)

    # doa = TimeDistributed(Dense(data_out[1][-1]))(doa)
    doa = Dense(data_out[1])(doa)
    doa = Activation('tanh', name='doa_out')(doa)

    # SED
    # sed = spec_rnn
    # for nb_fnn_filt in fnn_size:
    #     sed = TimeDistributed(Dense(nb_fnn_filt))(sed)
    #     sed = Dropout(dropout_rate)(sed)
    # sed = TimeDistributed(Dense(data_out[0][-1]))(sed)
    # sed = Activation('sigmoid', name='sed_out')(sed)

    model = Model(inputs=spec_start, outputs=doa)
    model.compile(optimizer=Adam(), loss='sparse_categorical_crossentropy', loss_weights=weights, metrics='acc')

    model.summary()
    return model
