import libtorrent as lt
import time
from constants import TORRENT_FILE_NAME as FILE_NAME, RUN_TIMES, NUM_CORES
from datetime import datetime
import multiprocessing
import os
import warnings

# suppress noisy libtorrent deprecation warnings for clearer output
warnings.filterwarnings("ignore", category=DeprecationWarning)


def download_torrent(progress_callback=None, stop_event=None, serial: bool = False, save_path: str = './downloads', title: str = None):
    print("Initializing download with serial:",
          serial, "-> save_path:", save_path)
    # ensure the target save directory exists (do not clear here; caller manages clearing)
    os.makedirs(save_path, exist_ok=True)
    session = lt.session()
    # standard ports for BitTorrent internet traffic
    session.listen_on(6881, 6891)

    # apply provided settings
    settings = get_settings_options(serial)
    session.apply_settings(settings)

    # add the torrent
    info = lt.torrent_info(FILE_NAME)
    torrent_handle = session.add_torrent(
        {'ti': info, 'save_path': save_path})

    # do not count time before connecting to the first seed
    start_time = datetime.now()

    if serial:
        torrent_handle.set_sequential_download(True)
    else:
        torrent_handle.set_sequential_download(False)

    print(
        f"Starting download (waiting for seed): {info.name()} -> {save_path}")

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
                  f"Title: {title} | "
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

            time.sleep(10)

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


class TorrentProcess(multiprocessing.Process):
    """A Process wrapper that runs `download_torrent` in a separate process.

    Usage:
        q = multiprocessing.Queue()
        p = TorrentProcess(result_queue=q)
        p.start()
        p.join()
        result = q.get()  # dict returned from download_torrent
    """

    def __init__(self, result_queue: multiprocessing.Queue = None,
                 progress_callback=None, stop_event=None, serial: bool = False,
                 save_path: str = None):
        super().__init__()
        self.result_queue = result_queue
        self.progress_callback = progress_callback
        self.stop_event = stop_event
        # The class will force serial=False when calling download_torrent
        # per the user's request. We still accept the param for API parity.
        self.serial = False
        # save_path for this process; if not provided, default to './downloads'
        self.save_path = save_path or './downloads'

    def run(self):
        try:
            result = download_torrent(progress_callback=self.progress_callback,
                                      stop_event=self.stop_event,
                                      serial=self.serial,
                                      save_path=self.save_path)
            if self.result_queue is not None:
                try:
                    self.result_queue.put(result)
                except Exception:
                    # last-resort: swallow queue errors to avoid crashing the child
                    pass
        except Exception as e:
            # If something goes wrong, put an error dict into the queue if available
            err = {'error': str(e)}
            if self.result_queue is not None:
                try:
                    self.result_queue.put(err)
                except Exception:
                    pass


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

    # prepare a fresh parent directory for the per-run downloads
    timestamp = int(_time.time())
    base_download_dir = f"./downloads/runs_{timestamp}"
    clear_downloads()
    os.makedirs(base_download_dir, exist_ok=True)

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

        # per-run save path ensures each run writes to its own folder
        save_path = os.path.join(base_download_dir, f"run_{run_idx}")
        os.makedirs(save_path, exist_ok=True)

        result = download_torrent(
            progress_callback=_inner_cb, stop_event=stop_event, serial=serial, save_path=save_path)

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
    mode_name = 'serial' if serial else 'parallel'
    filename = f"{timestamp}_{mode_name}.csv"
    results_dir = './results'
    try:
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

    return {'results': all_results, 'filename': filepath, 'base_download_dir': base_download_dir}


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


def download_torrents_process_parallel(serial: bool = False):
    num_runs = RUN_TIMES
    import time as _time
    from multiprocessing import Queue

    timestamp = int(_time.time())
    base_download_dir = f"./downloads/process_runs_{timestamp}"

    # clear previous downloads and create the base dir
    clear_downloads()
    os.makedirs(base_download_dir, exist_ok=True)

    result_queue = Queue()
    processes = []

    for i in range(num_runs):
        save_path = os.path.join(base_download_dir, f"run_{i+1}")
        os.makedirs(save_path, exist_ok=True)
        p = TorrentProcess(result_queue=result_queue, progress_callback=None,
                           stop_event=None, serial=serial, save_path=save_path)
        processes.append(p)

    # start all processes
    for p in processes:
        p.start()

    # wait for all to finish
    for p in processes:
        p.join()

    # collect results from the queue
    results = []
    while not result_queue.empty():
        try:
            results.append(result_queue.get_nowait())
        except Exception:
            break

    # If some processes didn't put a result, add placeholders
    if len(results) < num_runs:
        missing = num_runs - len(results)
        for _ in range(missing):
            results.append({'error': 'no result (process may have crashed)'})

    # write single CSV
    results_dir = './results'
    os.makedirs(results_dir, exist_ok=True)
    filename = f"{timestamp}_process_parallel.csv"
    filepath = os.path.join(results_dir, filename)
    try:
        with open(filepath, 'w') as fh:
            fh.write(
                'run,total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes,save_path\n')
            for i, r in enumerate(results, start=1):
                fh.write(
                    f"{i},{r.get('total_time_seconds', '')},{r.get('average_download_rate_kB_s', '')},{r.get('total_downloaded_bytes', '')},{r.get('save_path', '')}\n")
    except Exception as e:
        filepath = None
        print(f"Failed to write process-parallel CSV: {e}")

    return {'results': results, 'filename': filepath, 'base_download_dir': base_download_dir}


if __name__ == "__main__":
    input_mode = input(
        "Enter 'p' for single parallel download, 's' for single serial download, or 'cp' to download X torrents using CPU cores: ").strip().lower()
    if input_mode == 'p':
        clear_downloads()
        download_torrent(serial=False)
    elif input_mode == 's':
        clear_downloads()
        download_torrent(serial=True)
    elif input_mode == 'cp':
        clear_downloads()
        download_torrents_process_parallel()

    else:
        print("Invalid input. Please enter 'p', 's', or 'cp'.")
