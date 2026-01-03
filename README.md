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

- Choose `parallel` or `serial` mode.
- Click `Start` to begin. The GUI will plot progress (%) and download rate (kB/s).
- Click `Stop` to request cancellation.

Notes

- The GUI uses `client.download_torrent` via a background thread and receives a per-second status dict.
- The code for downloading torrent is in client.py
- Serial download is emulated by restricting download connections from libtorrent settings dict.
- The pyqt visualizer was made mostly using CoPilot. Promts used are at the top of the file.