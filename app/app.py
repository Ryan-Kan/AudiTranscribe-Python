"""
app.py

Created on 2021-11-16
Updated on 2022-02-06

Copyright © Ryan Kan

Description: Main flask application.
"""

# IMPORTS
import json
import os
import re
import shutil
import threading
from collections import defaultdict

import yaml
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, send_from_directory, abort
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from src.audio import estimate_bpm, get_audio_length, samples_to_vqt
from src.hashing import generate_hash_from_file
from src.io import audio_to_audiosegment, audiosegment_to_mp3, audiosegment_to_wav, wav_to_samples, \
    SUPPORTED_AUDIO_EXTENSIONS
from src.misc import MUSIC_KEYS, NOTE_NUMBER_RANGE
from src.visuals import generate_spectrogram_img

# CONSTANTS
# File constants
MAX_AUDIO_FILE_SIZE = {"Value": 10 ** 7, "Name": "10 MB"}
ACCEPTED_FILE_TYPES = [x.upper()[1:] for x in SUPPORTED_AUDIO_EXTENSIONS.keys()] + ["AUTR"]
CBR_MP3_BITRATE = 192  # In thousands

# Spectrogram settings
BATCH_SIZE = 32
PX_PER_SECOND = 120  # Number of pixels of the spectrogram dedicated to each second of audio
SPECTROGRAM_HEIGHT = 720  # Height of the spectrogram, in pixels

# Music settings
BEATS_PER_BAR_RANGE = [1, 8]  # In the format [min, max]
BPM_RANGE = [1, 512]  # In the format [min, max]

# FLASK SETUP
# Define basic things
app = Flask(__name__)
app.config.from_pyfile("base_config.py")

# Get the instance's `config.py` file
try:
    app.config.from_pyfile(os.path.join(app.instance_path, "config.py"))
except OSError:
    print("The instance's `config.py` file was not found. Using default settings. (INSECURE!)")

# Further app configuration
app.config["UPLOAD_FOLDER"] = "MediaFiles"
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_FILE_SIZE["Value"]

# Create the upload folder
try:
    os.mkdir(app.config["UPLOAD_FOLDER"])
except OSError:
    pass

# GLOBAL VARIABLES
processingThreads = defaultdict(lambda: {"phase": 0, "progress": []})


# HELPER FUNCTIONS
def allowed_file(filename: str):
    return "." in filename and filename.rsplit(".", 1)[1].upper() in ACCEPTED_FILE_TYPES


def processing_file(file: str, uuid: str, thread_data: dict):
    # Generate the folder path and status file path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Split the file into its filename and extension
    filename, extension = os.path.splitext(file)

    # Convert the audio file into an `AudioSegment` object
    thread_data["phase"] = 1  # Converting to audio segment
    audiosegment = audio_to_audiosegment(os.path.join(folder_path, file))

    # If the file is not a WAV file then convert it into one
    thread_data["phase"] = 2  # Generating WAV file
    if extension[1:].upper() != "WAV":
        audiosegment_to_wav(audiosegment, os.path.join(folder_path, filename))
        file_wav = os.path.join(folder_path, filename + ".wav")
    else:
        file_wav = os.path.join(folder_path, file)

    # Convert the audio file into a CBR MP3
    thread_data["phase"] = 3  # Generating CBR MP3
    audiosegment_to_mp3(audiosegment, os.path.join(folder_path, filename + "_cbr"), bitrate=CBR_MP3_BITRATE)

    # Update the status file on the audio file to reference
    update_status_file(
        os.path.join(folder_path, "status.yaml"),
        audio_file_name=filename + "_cbr.mp3"
    )

    # Now split the WAV file into samples
    thread_data["phase"] = 4  # Splitting into samples
    samples, sample_rate = wav_to_samples(file_wav)

    # We can now delete the old file and the WAV file
    try:
        os.remove(os.path.join(folder_path, file))
        os.remove(file_wav)
    except OSError:  # The files may be one and the same
        pass

    # Calculate the duration of the audio
    duration = get_audio_length(samples, sample_rate)

    # Convert the samples into a spectrogram
    thread_data["phase"] = 5  # Generating VQT data
    spectrogram, frequencies, times = samples_to_vqt(sample_rate, samples)

    # Convert the spectrogram data into a spectrogram image
    thread_data["phase"] = 6  # Generating spectrogram image
    image = generate_spectrogram_img(spectrogram, frequencies, times, duration, progress=thread_data["progress"],
                                     batch_size=BATCH_SIZE, px_per_second=PX_PER_SECOND, img_height=SPECTROGRAM_HEIGHT)

    # Save the image
    thread_data["phase"] = 7  # Saving spectrogram image
    image.save(os.path.join(folder_path, f"{filename}.png"))

    # Estimate the BPM of the sample
    thread_data["phase"] = 8  # Final touches
    bpm = int(estimate_bpm(samples, sample_rate)[0])  # Todo: support dynamic BPM

    # Update status file
    update_status_file(
        os.path.join(folder_path, "status.yaml"),
        spectrogram=f"{filename}.png",
        bpm=bpm,
        duration=duration,
        spectrogram_generated=True
    )
    thread_data["phase"] = 9  # Everything done


def update_status_file(status_file: str, **status_updates):
    # Load current status from file
    with open(status_file, "r") as f:
        status = yaml.load(f, yaml.Loader)

    # Update status
    for key, value in status_updates.items():
        status[key] = value

    # Dump updated status back to file
    with open(status_file, "w") as f:
        yaml.dump(status, f)


# FOLDER PATHS
@app.route("/media/<uuid>/<path:path>")
def send_media(uuid, path):
    # Generate the UUID's folder's path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Check if the UUID is valid
    if not os.path.isdir(folder_path):
        return abort(404)  # Not found

    return send_from_directory(os.path.join("..", folder_path), path)  # Go out of the "app" directory into the root


# API PAGES
@app.route("/api/delete-project/<uuid>", methods=["POST"])
def delete_project(uuid):
    # Generate the UUID's folder's path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Check if a folder with that UUID exists
    if not os.path.isdir(folder_path):
        return abort(404)

    # Delete the entire project folder
    shutil.rmtree(folder_path)

    # Redirect to main page
    flash(f"Project with UUID {uuid} was deleted.", category="msg")
    return json.dumps({
        "outcome": "ok",
        "url": url_for("main_page")
    })


@app.route("/api/download-quicklink/<uuid>", methods=["POST"])
def download_quicklink(uuid):
    # Generate the UUID's folder's path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Check if a folder with that UUID exists
    if not os.path.isdir(folder_path):
        return abort(404)

    # Send the status file
    return send_file(os.path.join("..", folder_path, "status.yaml"))


@app.route("/api/query-process/<uuid>", methods=["POST"])
def query_process(uuid):
    # Get the thread data associated with that UUID
    thread_data = processingThreads[uuid]

    # Get the phase and progress data
    phase = thread_data["phase"]
    progress = thread_data["progress"]

    # Handle each phase correctly
    if phase == 0:  # Uploaded audio file
        return_data = {"Message": "Starting to process spectrogram."}
    elif phase == 1:  # Converting to audio segment
        return_data = {"Message": "Converting to audio segment data."}
    elif phase == 2:  # Generating WAV file
        return_data = {"Message": "Generating WAV file."}
    elif phase == 3:  # Generating CBR MP3
        return_data = {"Message": "Generating constant bitrate MP3 file."}
    elif phase == 4:  # Splitting into samples
        return_data = {"Message": "Splitting audio into smaller samples."}
    elif phase == 5:  # Generating VQT data
        return_data = {"Message": "Generating spectrogram data."}
    elif phase == 6:  # Generating spectrogram image
        # Get the latest value in the progress
        if progress[0] is None:  # Nothing processed yet
            batch_no = 0
            num_batches = 100  # Assume 100 batches
        else:
            batch_no, num_batches = progress[0]

        # Calculate the progress percentage
        progress_percentage = int(batch_no / num_batches * 100)  # As a number in the interval [0, 100]

        # Generate the return data
        return_data = {"Message": "Generating spectrogram image.", "Progress": progress_percentage}
    elif phase == 7:  # Saving spectrogram image
        return_data = {"Message": "Saving spectrogram image."}
    elif phase == 8:  # Final touches
        return_data = {"Message": "Performing final touches."}
    else:  # Phase 9; updated status file
        return_data = {"Message": "Updated status file. Redirecting in a short while...", "Progress": 100}

    return json.dumps(return_data)


@app.route("/api/save-project/<uuid>", methods=["POST"])
def save_project(uuid):
    # Generate the UUID's folder's path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Check if a folder with that UUID exists
    if not os.path.isdir(folder_path):
        return json.dumps({"outcome": "error", "msg": "UUID doesn't exist."})

    # Update the status file
    update_status_file(os.path.join(folder_path, "status.yaml"), **request.json)

    # Send the status file
    return json.dumps({"outcome": "ok", "msg": "Project saved successfully."})


@app.route("/api/upload-file", methods=["POST"])
def upload_file():
    # Check if the request has the file
    if "file" not in request.files:
        return json.dumps({"outcome": "error", "msg": "No file uploaded."})

    # Get the file
    file = request.files["file"]

    # Check if the file is empty or not
    if file.filename == "":
        return json.dumps({"outcome": "error", "msg": "File is empty."})

    # Check if the file is of the correct extension
    if not allowed_file(file.filename):
        return json.dumps({
            "outcome": "error",
            "msg": f"File does not have correct format. Accepted: {', '.join(ACCEPTED_FILE_TYPES)}."
        })

    # Check if this is an existing project file
    if os.path.splitext(file.filename)[-1].upper() == ".AUTR":
        # Read the contents of the .autr file as an YAML file
        existing_project = yaml.load(file.stream, yaml.Loader)

        # Get the UUID
        existing_uuid = existing_project["uuid"]

        # Provide the link to the existing page
        return json.dumps({
            "outcome": "ok",
            "msg": "Redirecting to existing project.",
            "url": url_for("transcriber", uuid=existing_uuid)
        })

    # If not existing project, save the file
    initial_file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(initial_file_path)

    # Generate the file's UUID based on its contents
    uuid = generate_hash_from_file(initial_file_path)

    # Check if a UUID like that already exists
    try:
        folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)
        os.mkdir(folder_path)
    except OSError:  # Folder exists => UUID exists => There already exists an existing file
        # Delete the file on the MAIN directory
        os.remove(initial_file_path)

        # Provide the link to the existing page
        return json.dumps({
            "outcome": "ok",
            "msg": "Redirecting to existing project.",
            "url": url_for("transcriber", uuid=uuid)
        })

    # If it is not an existing file, move the file into the created directory
    final_file_path = os.path.join(folder_path, file.filename)
    shutil.move(initial_file_path, final_file_path)

    # Get the file's extension
    _, extension = os.path.splitext(file.filename)

    # Check if the file is readable
    try:
        AudioSegment.from_file(os.path.join(folder_path, file.filename), SUPPORTED_AUDIO_EXTENSIONS[extension])
    except (IndexError, CouldntDecodeError):
        # Delete the file and folder from the server
        os.remove(os.path.join(folder_path, file.filename))
        os.rmdir(folder_path)

        # Return the error message
        return json.dumps({
            "outcome": "error",
            "msg": f"File supposedly of type {extension[1:]} but couldn't decode."
        })

    # Create a blank status dictionary
    status_blank = {
        "uuid": uuid,
        "original_file_name": file.filename,
        "audio_file_name": None,
        "spectrogram_generated": False
    }

    # Create a status file
    with open(os.path.join(folder_path, "status.yaml"), "w") as f:
        yaml.dump(status_blank, f)

    # Provide the link to another page for the analysis of that audio file
    return json.dumps({
        "outcome": "ok",
        "msg": "Upload successful. Redirecting.",
        "url": url_for("transcriber", uuid=uuid)
    })


# WEBSITE PAGES
@app.route("/")
def main_page():
    return render_template("main_page.html", max_audio_file_size=json.dumps(MAX_AUDIO_FILE_SIZE),
                           accepted_file_types=ACCEPTED_FILE_TYPES)


@app.route("/licenses")
def licenses():
    return render_template("licenses.html")


@app.route("/transcriber/<uuid>")
def transcriber(uuid):
    # Generate the UUID's folder's path
    folder_path = os.path.join(app.config["UPLOAD_FOLDER"], uuid)

    # Check if a folder with that UUID exists
    if not os.path.isdir(folder_path):
        flash(f"The UUID {uuid} does not exist.", category="msg")
        return redirect(url_for("main_page"))

    # Read the status file
    with open(os.path.join(folder_path, "status.yaml"), "r") as f:
        status = yaml.load(f, yaml.Loader)

    # Check whether the CBR MP3 file was created yet
    audio_file_name = status["audio_file_name"]

    if audio_file_name is None:  # CBR MP3 not yet created
        # Create a location to store the spectrogram generation progress
        processingThreads[uuid]["progress"].append(None)  # One-element list for data sharing

        # Start a multiprocessing thread and save it to the master dictionary
        thread = threading.Thread(target=processing_file,
                                  args=(status["original_file_name"], uuid, processingThreads[uuid]))
        thread.start()
        processingThreads[uuid]["thread"] = thread

        # Render the template
        return render_template("transcriber.html", spectrogram_generated=False, uuid=uuid,
                               file_name=status["original_file_name"], file_name_proper=status["original_file_name"])
    else:
        # Check whether the spectrogram has been generated or not
        spectrogram_generated = status["spectrogram_generated"]

        if not spectrogram_generated:
            # Render the template
            return render_template("transcriber.html", spectrogram_generated=False, uuid=uuid,
                                   file_name=status["audio_file_name"],
                                   file_name_proper=re.sub(r"_cbr(?!.*_cbr)+", "", status["audio_file_name"]))
        else:
            # Try and delete the process thread
            if processingThreads[uuid]:
                del processingThreads[uuid]

            # Render the template with the variables
            return render_template("transcriber.html", spectrogram_generated=True, uuid=uuid,
                                   file_name=status["audio_file_name"],
                                   file_name_proper=re.sub(r"_cbr(?!.*_cbr)+", "", status["audio_file_name"]),
                                   status=json.dumps(status), beats_per_bar_range=BEATS_PER_BAR_RANGE,
                                   bpm_range=BPM_RANGE, music_keys=MUSIC_KEYS, note_number_range=NOTE_NUMBER_RANGE,
                                   px_per_second=PX_PER_SECOND)


# TESTING CODE
if __name__ == "__main__":
    app.run(threaded=True)
