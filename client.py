import libtorrent as lt
import time
from constants import TORRENT_FILE_NAME as FILE_NAME, RUN_TIMES, NUM_CORES
from datetime import datetime
import multiprocessing
import os
import warnings

# suppress noisy libtorrent deprecation warnings for clearer output
warnings.filterwarnings("ignore", category=DeprecationWarning)


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
    start_time = datetime.now()

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


def _download_single_torrent_worker(torrent_path, save_path, serial=True, timeout_seconds: int = 600):
    """Worker that downloads a single torrent to `save_path` and returns stats.

    This runs in a separate process so it must be a top-level function.
    """
    import libtorrent as lt
    from datetime import datetime
    import time as _time

    # ensure save path exists
    os.makedirs(save_path, exist_ok=True)

    session = lt.session()
    # let the OS pick an available port range for each worker to avoid bind conflicts
    session.listen_on(0, 0)

    settings = get_settings_options(serial)
    session.apply_settings(settings)

    info = lt.torrent_info(torrent_path)
    torrent_handle = session.add_torrent({'ti': info, 'save_path': save_path})

    start_time = datetime.now()
    # small startup message so we can see progress when many processes run
    try:
        print(f"[pid {os.getpid()}] Starting: {info.name()} -> {save_path}")
    except Exception:
        print(f"[pid {os.getpid()}] Starting torrent -> {save_path}")
    if serial:
        torrent_handle.set_sequential_download(True)
    else:
        torrent_handle.set_sequential_download(False)

    sum_download_rate = 0
    download_count = 0

    timed_out = False
    try:
        while not torrent_handle.status().is_seeding:
            status = torrent_handle.status()
            sum_download_rate += status.download_rate
            download_count += 1

            # check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if timeout_seconds and elapsed > timeout_seconds:
                try:
                    print(
                        f"[pid {os.getpid()}] Timeout reached ({timeout_seconds}s) for {info.name()}")
                except Exception:
                    print(
                        f"[pid {os.getpid()}] Timeout reached ({timeout_seconds}s)")
                timed_out = True
                break

            _time.sleep(0.1)
    except KeyboardInterrupt:
        timed_out = False

    # collect final stats
    final_status = torrent_handle.status()
    data = {
        'average_download_rate_kB_s': (sum_download_rate / download_count) / 1000 if download_count > 0 else 0,
        'total_downloaded_bytes': final_status.total_done,
        'total_time_seconds': (datetime.now() - start_time).total_seconds() if start_time is not None else 0,
        'torrent_name': info.name(),
        'save_path': save_path,
    }

    print(
        f"[pid {os.getpid()}] Completed: {info.name() if not timed_out else 'Timed out'} -> {save_path} | total_time_seconds: {data['total_time_seconds']}")
    return data


def download_torrents_parallel(num_torrents: int, num_cores: int, serial: bool = False):
    """Download `num_torrents` torrents using up to `num_cores` CPU cores in parallel.

    - `torrent_files` can be a list of torrent-file paths (strings). If not provided,
      the configured `FILE_NAME` will be used repeatedly.
    - Each download runs in its own process and writes into `./downloads/parallel_<ts>/torrent_<i>`.
    - Returns a dict with `results` (list of per-download dicts) and `base_dir`.
    """
    import time as _time

    clear_downloads()

    print(
        f"Starting {num_torrents} downloads using {num_cores} cores (serial={serial})...")

    torrent_files = [FILE_NAME] * num_torrents
    num_cores = max(1, int(num_cores))
    base_results_dir = f"./downloads/parallel_{int(_time.time())}"
    os.makedirs(base_results_dir, exist_ok=True)

    tasks = []
    for i in range(num_torrents):
        save_path = os.path.join(base_results_dir, f"torrent_{i + 1}")
        # ensure per-download folder exists (create from parent so it's visible immediately)
        try:
            os.makedirs(save_path, exist_ok=True)
            print(f"Created save path: {save_path}")
        except Exception:
            print(f"Failed to create save path: {save_path}")
        tasks.append((torrent_files[i], save_path, serial))

    # start wall-clock timer for the whole parallel run
    start_wall = time.time()

    pool = multiprocessing.Pool(processes=num_cores)
    try:
        results = pool.starmap(_download_single_torrent_worker, tasks)
    finally:
        pool.close()
        pool.join()

    total_time_seconds = time.time() - start_wall

    # aggregate totals across child downloads
    total_downloaded_bytes = sum(
        [r.get('total_downloaded_bytes', 0) for r in results])
    average_download_rate_kB_s = (
        total_downloaded_bytes / total_time_seconds) / 1000 if total_time_seconds > 0 else 0

    summary = {
        'total_time_seconds': total_time_seconds,
        'total_downloaded_bytes': total_downloaded_bytes,
        'average_download_rate_kB_s': average_download_rate_kB_s,
        'base_dir': base_results_dir,
        'num_torrents': num_torrents,
        'num_cores': num_cores,
    }

    return {'results': results, 'base_dir': base_results_dir, 'summary': summary}


if __name__ == "__main__":
    input_mode = input(
        "Enter 'p' for single parallel download, 's' for single serial download, or 'cp' to download X torrents using CPU cores: ").strip().lower()
    if input_mode == 'p':
        download_torrent(serial=False)
    elif input_mode == 's':
        download_torrent(serial=True)
    elif input_mode == 'cp':
        num_cores = min(NUM_CORES, multiprocessing.cpu_count())
        num_torrents = RUN_TIMES
        print(f"Starting {num_torrents} downloads using {num_cores} cores...")
        result = download_torrents_parallel(
            num_torrents=num_torrents, num_cores=num_cores)

        # export aggregated summary to CSV
        try:
            summary = result.get('summary', {})
            timestamp = int(time.time())
            filename = f"{timestamp}_cpu-parallel-summary.csv"
            results_dir = './results'
            os.makedirs(results_dir, exist_ok=True)
            filepath = os.path.join(results_dir, filename)
            with open(filepath, 'w') as fh:
                fh.write(
                    'total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes,base_dir,num_torrents,num_cores\n')
                fh.write(f"{summary.get('total_time_seconds', 0)},{summary.get('average_download_rate_kB_s', 0)},{summary.get('total_downloaded_bytes', 0)},{summary.get('base_dir', '')},{summary.get('num_torrents', 0)},{summary.get('num_cores', 0)}\n")
            print(f"Summary results written to: {filepath}")
        except Exception as e:
            print(f"Failed to write summary results file: {e}")

    else:
        print("Invalid input. Please enter 'p', 's', or 'cp'.")
