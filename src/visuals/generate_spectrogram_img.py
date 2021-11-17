"""
generate_spectrogram_img.py

Created on 2021-11-16
Updated on 2021-11-17

Copyright © Ryan Kan

Description: Code that generates a spectrogram image.
"""

# IMPORTS
import io
import math
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from tqdm import trange


# FUNCTIONS
def generate_spectrogram_img(spectrogram: np.ndarray, frequencies: np.ndarray, times: np.ndarray,
                             progress: Optional[list] = None, batch_size: int = 100, px_per_second: int = 50,
                             img_height=720, dpi: float = 100.) -> Image.Image:
    """
    Generates a spectrogram image.

    Args:
        spectrogram:
             Matrix of short-term Fourier transform coefficients, i.e. the spectrogram data.

        frequencies:
            Array of sample frequencies.

        times:
            Array of sample times.

        progress:
            List object to share the spectrogram processing process with other threads.
            A list is used instead of a standard tuple to utilise address assignment of lists, and so the data can be
            shared across threads.
            (Default: None)

        batch_size:
            Size of each batch when generating each image.
            (Default: 100)

        px_per_second:
            Number of pixels of the spectrogram dedicated to each second of audio.
            (Default: 64)

        img_height:
            Height of the image, in pixels.
            (Default: 720)

        dpi:
            The resolution of the figure in dots-per-inch.
            (Default: 100.0)

    Returns:
        spectrogram_image

    Todo:
        Allow this to 'output' some progress data that can be read by Python code (NOT tqdm progess bars).
    """

    # Get the number of samples
    num_samples = len(times)

    # Calculate the number of batches needed
    num_batches = math.ceil(num_samples / batch_size)

    # Determine what iterable to use
    if progress is None:
        iterable = trange(num_batches, desc="Iterating through batches")
    else:
        iterable = range(num_batches)

    # Generate all images
    images = []

    for batch_no in iterable:
        # Get the length of the audio
        if batch_no != num_batches - 1:  # Not last batch
            audio_length = times[(batch_no + 1) * batch_size - 1] - times[batch_no * batch_size]
        else:
            audio_length = times[-1] - times[(num_batches - 1) * batch_size]

        # Create the figure and axis
        fig = plt.Figure(figsize=(audio_length * px_per_second / dpi, img_height / dpi), dpi=dpi)
        ax = plt.Axes(fig, [0., 0., 1., 1.])
        fig.add_axes(ax)

        # Plot the spectrogram
        if batch_no != num_batches - 1:  # Not last batch
            ax.pcolormesh(
                times[batch_no * batch_size: (batch_no + 1) * batch_size - 1],
                frequencies,  # Want ALL frequencies
                spectrogram[:, batch_no * batch_size: (batch_no + 1) * batch_size - 1],
                shading="gouraud"
            )
        else:
            ax.pcolormesh(
                times[(num_batches - 1) * batch_size:],
                frequencies,  # Want ALL frequencies
                spectrogram[:, (num_batches - 1) * batch_size:],
                shading="gouraud"
            )

        ax.set_axis_off()  # Remove axis labels

        # Save the spectrogram to the image buffer
        img_buf = io.BytesIO()
        fig.savefig(img_buf, bbox_inches="tight", pad_inches=0)  # No whitespace

        # Open the image buffer in Pillow
        img = Image.open(img_buf)

        # Append the generated image to the list of all images
        images.append(img)

        # Update the progress, if required
        if progress is not None:
            progress[0] = (batch_no, num_batches)  # Set the only element in the list to be the progress

    # Get the combined length of all images
    combined_length = 0
    for img in images:
        combined_length += img.width

    # Merge all images into one giant image
    final_img = Image.new("RGB", (combined_length, img_height))
    curr_length = 0  # Used for determination on where to paste the image

    for i, img in enumerate(images):
        final_img.paste(img, box=(curr_length, 0))  # Note that the uppermost edge is 0
        curr_length += img.width

    # Return the pillow image
    return final_img


# TESTING CODE
if __name__ == "__main__":
    # Imports
    from src.audio import wav_samples_to_spectrogram
    from src.io import wav_to_samples

    # Read the testing WAV file
    samples_, sample_rate_ = wav_to_samples("../../Testing Files/Fly.wav")

    # Convert to spectrogram
    spec, freq, time = wav_samples_to_spectrogram(sample_rate_, samples_)

    # Display spectrogram
    image = generate_spectrogram_img(spec, freq, time)
    image.show(title="Spectrogram Image")
