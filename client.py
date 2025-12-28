import libtorrent as lt
import time
from constants import TORRENT_FILE_NAME as FILE_NAME, RUN_TIMES
from datetime import datetime


def download_torrent(progress_callback=None, stop_event=None, serial: bool = False):
    print("Initializing download with serial:", serial)
    clear_downloads()
    session = lt.session()
    # standard ports for BitTorrent internet traffic
    session.listen_on(6881, 6891)

    # apply provided settings
    settings = get_settings_options(serial)
    session.apply_settings(settings)

    # add the torrent
    info = lt.torrent_info(FILE_NAME)
    torrent_handle = session.add_torrent(
        {'ti': info, 'save_path': './downloads'})

    # do not count time before connecting to the first seed
    start_time = None
    started = False

    if serial:
        torrent_handle.set_sequential_download(True)
    else:
        torrent_handle.set_sequential_download(False)

    print(f"Starting download (waiting for seed): {info.name()}")

    # monitoring loop

    sum_download_rate = 0
    download_count = 0

    try:
        while not torrent_handle.status().is_seeding:
            # allow external cancellation
            if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                break

            status = torrent_handle.status()
            # start timing and counting only after we see a seed
            if not started and status.num_seeds > 0:
                started = True
                start_time = datetime.now()
                print(
                    "Connected to seed, starting download. Start time is - ", start_time)

            if started:
                sum_download_rate += status.download_rate
                download_count += 1

            # status dict for GUI consumers
            time_spent = (
                datetime.now() - start_time).total_seconds() if start_time is not None else 0
            status_dict = {
                'progress': status.progress,  # 0..1
                'download_rate': status.download_rate,  # bytes/s
                'num_peers': status.num_peers,
                'num_seeds': status.num_seeds,
                'state': str(status.state),
                'total_done': status.total_done,
                'total_time': time_spent,
            }

            # print to console as before
            print(f"\r{status.progress * 100:.2f}% | "
                  f"Down: {status.download_rate / 1000:.1f} kB/s | "
                  f"Peers: {status.num_peers} | "
                  f"Seeds: {status.num_seeds} | "
                  f"State: {status.state} | ")

            # emit progress for GUI
            if progress_callback is not None:
                try:
                    progress_callback(status_dict)
                except Exception:
                    # swallow GUI callback errors to keep download running
                    pass

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nAborted.")

    print("\nDownload complete!")

    data = {
        'average_download_rate_kB_s': (sum_download_rate / download_count) / 1000 if download_count > 0 else 0,
        'total_downloaded_bytes': torrent_handle.status().total_done,
        'total_time_seconds': (datetime.now() - start_time).total_seconds() if start_time is not None else 0,
    }
    print(
        f"Average Download Rate: {data['average_download_rate_kB_s']:.2f} kB/s")

    return data


def get_settings_options(serial: bool):
    if serial:
        return {
            # limit to 1 connection to prevent parallel downloading from multiple peers
            'connections_limit': 1,

            # disable pipelining: only 1 outstanding request at a time
            'max_out_request_queue': 1,
            'max_allowed_in_request_queue': 1,

            # set sequential download order
            'mixed_mode_algorithm': 0,
        }
    else:
        return {
            'enable_dht': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'connections_limit': 10,
            'max_out_request_queue': 1,  # per peer
        }


def download_torrent_for_results(progress_callback=None, stop_event=None, serial: bool = False):
    import time as _time
    all_results = []

    for run in range(RUN_TIMES):
        run_idx = run + 1
        print(f"\n--- Run {run_idx} of {RUN_TIMES} ---")

        # inner callback wraps per-second status with run index
        def _inner_cb(status, _run=run_idx):
            if progress_callback is not None:
                try:
                    progress_callback(
                        {'type': 'status', 'data': status, 'run': _run})
                except Exception:
                    pass

        result = download_torrent(
            progress_callback=_inner_cb, stop_event=stop_event, serial=serial)

        all_results.append(result)

        # emit run_done
        if progress_callback is not None:
            try:
                progress_callback(
                    {'type': 'run_done', 'data': result, 'run': run_idx})
            except Exception:
                pass

        # if stop requested, break early
        if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
            break

    # write results to results/<timestamp>_mode.csv
    timestamp = int(_time.time())
    mode_name = 'serial' if serial else 'parallel'
    filename = f"{timestamp}_{mode_name}.csv"
    results_dir = './results'
    try:
        import os
        os.makedirs(results_dir, exist_ok=True)
        filepath = os.path.join(results_dir, filename)
        with open(filepath, 'w') as fh:
            fh.write(
                'run,total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes\n')
            for i, r in enumerate(all_results, start=1):
                fh.write(
                    f"{i},{r.get('total_time_seconds', 0)},{r.get('average_download_rate_kB_s', 0)},{r.get('total_downloaded_bytes', 0)}\n")
    except Exception as e:
        filepath = None
        print(f"Failed to write results file: {e}")

    return {'results': all_results, 'filename': filepath}


def clear_downloads():
    import os
    import shutil

    download_path = './downloads'
    if os.path.exists(download_path):
        shutil.rmtree(download_path)
        print("Cleared downloads.")
    else:
        print("No downloads to clear.")


if __name__ == "__main__":
    input_mode = input(
        "Enter 'p' for parallel download or 's' for serial download: ").strip().lower()
    if input_mode == 'p':
        download_torrent(serial=False)
    elif input_mode == 's':
        download_torrent(serial=True)
    else:
        print("Invalid input. Please enter 'p' or 's'.")
