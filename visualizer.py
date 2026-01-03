#!/usr/bin/env python3
"""
Simple PyQt5 visualizer for the torrent downloader.

Usage: `python3 visualizer.py`

This GUI starts a download using the existing `client.py` functions and
receives per-second updates via a callback. It plots progress and download
rate so you can compare serial vs parallel modes.

Promts used to make this file:
"Write a pyqt program that visualizes the download and shows difference of serial and parallel download from this script."
"Nice. After the download is done, show total time spent and avg download speed in GUI"

Few bugs needed to be fixed after the prompts.

"""
import sys
import threading
import queue
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

import client
import os
import shutil
import time


class DownloadWorker(threading.Thread):
    def __init__(self, progress_q, stop_event, mode='parallel', serial=False):
        super().__init__(daemon=True)
        self.progress_q = progress_q
        self.stop_event = stop_event
        self.mode = mode
        self.serial = serial

    def run(self):
        # progress_callback expected by client.download_torrent_for_results
        def cb(message):
            # client will send dicts with 'type' key ('status'|'run_done')
            try:
                self.progress_q.put(message)
            except Exception:
                pass

        try:
            # choose function based on requested mode
            if getattr(self, 'mode', 'parallel') == 'full-parallel':
                result = client.download_torrent_full_parallel(
                    progress_callback=cb, stop_event=self.stop_event)
            else:
                result = client.download_torrent_for_results(
                    progress_callback=cb, stop_event=self.stop_event, serial=self.serial)
            # result is a dict {'results': [...], 'filename': path}
            self.progress_q.put({'type': 'done', 'data': result})
        except Exception as e:
            self.progress_q.put({'type': 'error', 'data': str(e)})


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ParAlgoTorrent Visualizer')
        self.resize(900, 600)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Controls
        ctrl_layout = QtWidgets.QHBoxLayout()
        self.mode_combo = QtWidgets.QComboBox()
        # add new full-parallel mode option
        self.mode_combo.addItems(['parallel', 'serial', 'full-parallel'])
        ctrl_layout.addWidget(QtWidgets.QLabel('Mode:'))
        ctrl_layout.addWidget(self.mode_combo)

        self.start_btn = QtWidgets.QPushButton('Start')
        self.start_btn.clicked.connect(self.start_download)
        ctrl_layout.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)
        ctrl_layout.addWidget(self.stop_btn)

        layout.addLayout(ctrl_layout)

        # Info labels
        info_layout = QtWidgets.QHBoxLayout()
        self.progress_label = QtWidgets.QLabel('Progress: 0.00%')
        self.rate_label = QtWidgets.QLabel('Rate: 0.0 kB/s')
        self.peers_label = QtWidgets.QLabel('Peers: 0')
        # run counter label
        self.run_label = QtWidgets.QLabel('Run: 0/0')
        # final summary labels (updated when download finishes)
        self.total_time_label = QtWidgets.QLabel('Total time: -')
        self.avg_rate_label = QtWidgets.QLabel('Avg rate: -')

        info_layout.addWidget(self.progress_label)
        info_layout.addWidget(self.rate_label)
        info_layout.addWidget(self.peers_label)
        info_layout.addWidget(self.run_label)
        info_layout.addWidget(self.total_time_label)
        info_layout.addWidget(self.avg_rate_label)
        layout.addLayout(info_layout)

        # Plots
        plots = QtWidgets.QHBoxLayout()
        self.progress_plot = pg.PlotWidget(title='Progress (%)')
        self.progress_plot.setYRange(0, 100)
        self.progress_curve = self.progress_plot.plot([], [], pen='g')
        plots.addWidget(self.progress_plot)

        self.rate_plot = pg.PlotWidget(title='Download Rate (kB/s)')
        self.rate_curve = self.rate_plot.plot([], [], pen='c')
        plots.addWidget(self.rate_plot)

        layout.addLayout(plots)

        # internal
        self.progress_q = queue.Queue()
        self.stop_event = None
        self.worker = None
        self.x = []
        self.y_progress = []
        self.y_rate = []
        self.sample_idx = 0

        # Timer to pull from queue and update GUI
        self.timer = QtCore.QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _mode_settings(self, mode):
        if mode == 'parallel':
            return {
                'enable_dht': True,
                'enable_upnp': True,
                'enable_natpmp': True,
            }
        else:
            return {
                'connections_limit': 1,
                'max_out_request_queue': 1,
                'max_allowed_in_request_queue': 1,
                'mixed_mode_algorithm': 0,
            }

    def start_download(self):
        mode = self.mode_combo.currentText()
        # visualizer delegates downloads and saving to client; only show data
        self.progress_q.queue.clear() if hasattr(self.progress_q, 'queue') else None
        self.x.clear()
        self.y_progress.clear()
        self.y_rate.clear()
        self.sample_idx = 0
        self.progress_curve.setData([], [])
        self.rate_curve.setData([], [])

        serial = True if mode == 'serial' else False
        total_runs = getattr(client, 'RUN_TIMES', '?')
        self.run_label.setText(f'Run: 0/{total_runs}')

        self.stop_event = threading.Event()
        mode = self.mode_combo.currentText()
        self.worker = DownloadWorker(
            self.progress_q, self.stop_event, mode=mode, serial=serial)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_download(self):
        if self.stop_event is not None:
            self.stop_event.set()
        self.stop_btn.setEnabled(False)

    def _poll(self):
        updated = False
        try:
            while True:
                item = self.progress_q.get_nowait()
                t = item.get('type')
                if t == 'status':
                    s = item['data']
                    run = item.get('run', 0)
                    # update run label
                    total_runs = getattr(client, 'RUN_TIMES', '?')
                    self.run_label.setText(f'Run: {run}/{total_runs}')

                    self.sample_idx += 1
                    self.x.append(self.sample_idx)
                    self.y_progress.append(s['progress'] * 100)
                    self.y_rate.append(s['download_rate'] / 1000.0)

                    self.progress_curve.setData(self.x, self.y_progress)
                    self.rate_curve.setData(self.x, self.y_rate)

                    self.progress_label.setText(
                        f"Progress: {s['progress']*100:.2f}%")
                    self.rate_label.setText(
                        f"Rate: {s['download_rate']/1000.0:.1f} kB/s")
                    self.peers_label.setText(
                        f"Peers: {s['num_peers']} (Seeds: {s['num_seeds']})")
                    updated = True

                elif t == 'run_done':
                    # one run finished; update final labels with this run's results
                    run = item.get('run', 0)
                    data = item['data']
                    total_time = data.get('total_time_seconds')
                    avg_rate = data.get('average_download_rate_kB_s')
                    if total_time is not None:
                        self.total_time_label.setText(
                            f"Total time: {total_time:.1f} s")
                    if avg_rate is not None:
                        self.avg_rate_label.setText(
                            f"Avg rate: {avg_rate:.2f} kB/s")
                    # reset sample buffers for next run
                    self.sample_idx = 0
                    self.x.clear()
                    self.y_progress.clear()
                    self.y_rate.clear()
                    self.progress_curve.setData([], [])
                    self.rate_curve.setData([], [])

                elif t == 'done':
                    # final summary (results written to file)
                    payload = item['data']
                    if isinstance(payload, dict) and 'filename' in payload:
                        fname = payload['filename']
                        QtWidgets.QMessageBox.information(
                            self, 'All Runs Done', f"All runs finished. Results saved to: {fname}")
                    else:
                        # legacy single-run done
                        data = payload
                        total_time = data.get('total_time_seconds')
                        avg_rate = data.get('average_download_rate_kB_s')
                        if total_time is not None:
                            self.total_time_label.setText(
                                f"Total time: {total_time:.1f} s")
                        if avg_rate is not None:
                            self.avg_rate_label.setText(
                                f"Avg rate: {avg_rate:.2f} kB/s")
                        QtWidgets.QMessageBox.information(
                            self, 'Done', f"Download finished. Total time: {total_time:.1f} s\nAvg rate: {avg_rate:.2f} kB/s")
                    self._finish()
                    return
                elif t == 'error':
                    QtWidgets.QMessageBox.critical(
                        self, 'Error', f"Error: {item['data']}")
                    self._finish()
                    return
        except queue.Empty:
            pass

    def _finish(self):
        self.start_btn.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_event = None
        self.worker = None


def main():
    app = QtWidgets.QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
