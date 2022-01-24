"""
samples_to_stft.py

Created on 2021-11-14
Updated on 2021-12-21

Copyright © Ryan Kan

Description: Converts the samples of a WAV file into a short-time fourier transform (STFT) matrix.
"""

# IMPORTS
from typing import Tuple

import librosa
import numpy as np


# FUNCTIONS
def samples_to_stft(sample_rate: float, samples: np.array, n_fft: int = 16384,
                    hop_length: int = 1024) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Converts the samples of a WAV file into a STFT matrix.

    Args:
        sample_rate:
            Sample rate of the WAV file.

        samples:
            Data read from WAV file.

        n_fft:
            Length of the windowed signal after padding with zeros. This partially controls the frequency-resolution of
            the STFT (higher `n_fft` -> higher frequency-resolution). See
            https://librosa.org/doc/main/generated/librosa.stft.html for more information.
            (Default: 16384)

        hop_length:
            Number of audio samples between adjacent STFT columns. This partially controls the time-resolution of the
            STFT (higher `hop_length` -> lower time-resolution). See
            https://librosa.org/doc/main/generated/librosa.stft.html for more information.
            (Default: 1024)

    Returns:
        stft:
            Matrix of short-term Fourier transform coefficients, i.e. the spectrogram data.

        frequencies:
            Array of sample frequencies.

        times:
            Array of sample times.
    """

    # Generate the STFT of the audio file
    stft = librosa.stft(samples, n_fft=n_fft, hop_length=hop_length)

    # Keep only the magnitude of the complex numbers from the STFT
    spectrogram = np.abs(stft)

    # Get the possible frequencies from the spectrogram
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)

    # Convert the amplitude of the sound to decibels
    spectrogram = librosa.amplitude_to_db(spectrogram, ref=np.max)

    # Get the time data
    frame_numbers = np.arange(spectrogram.shape[1])  # Get the time axis size
    times = librosa.frames_to_time(frame_numbers, sr=sample_rate, hop_length=hop_length, n_fft=n_fft)

    # Return the STFT, frequencies and times
    return spectrogram, frequencies, times


# TESTING CODE
if __name__ == "__main__":
    # Imports
    from src.io import wav_to_samples

    # Read the testing WAV file
    samples_, sample_rate_ = wav_to_samples("../../../Testing Files/Melancholy.wav")

    # Convert to spectrogram
    spec, freq, time = samples_to_stft(sample_rate_, samples_)

    # Print them
    print(spec)
    print(freq)
    print(time)