# ParAlgoTorrent Visualizer

This small GUI demonstrates and visualizes serial vs parallel downloads using the existing `client.py` code in this repository.

Quick start

1. Install python3 from https://www.python.org/downloads/

2. Create a python virtual environmennt
```
python3 -m venv venv
```

3. Install dependencies:
```bash
python3 -m pip install -r requirements.txt
```

3. Run the visualizer:

```bash
python3 visualizer.py
```

You can also run the `client.py` from terminal if you want.


Usage
# ParAlgoTorrent Visualizer

This small GUI demonstrates and visualizes serial vs parallel downloads using the existing `client.py` code in this repository.

Quick start

1. Install python3 from https://www.python.org/downloads/

2. Create a python virtual environment

```bash
python3 -m venv venv
```

3. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

4. Run the visualizer:

```bash
python3 visualizer.py
```

Usage

- Choose `parallel`, `serial`, or the new `full-parallel` mode.
- Click `Start` to begin. The GUI will plot progress (%) and download rate (kB/s).
- Click `Stop` to request cancellation.


You can also run the `client.py` from terminal if you prefer.

GUI notes

- Select `full-parallel` from the Mode dropdown to run the all-at-once experiment from the visualizer.
- The visualizer receives per-handle status updates during the run and will show a final popup with the results file.

Notes

- Downloads are stored under `./downloads` (the script clears this folder before each run).
- Results are written to `./results/` with timestamped filenames.
- Dependencies: see `requirements.txt` (includes `libtorrent`, `PyQt5`, `pyqtgraph` for GUI).

If you want the GUI to display the `all_finished_time_seconds` prominently or emit per-run `run_done` events during the full-parallel run, I can update the visualizer accordingly.