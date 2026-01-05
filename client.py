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
    start_time = datetime.now()

    if serial:
        torrent_handle.set_sequential_download(True)
    else:
        torrent_handle.set_sequential_download(False)

    print(f"Starting download (waiting for seed): {info.name()}")

    # helper: safe attribute access and metric extraction
    def _safe_get(obj, *names):
        for n in names:
            try:
                if hasattr(obj, n):
                    v = getattr(obj, n)
                    # call if callable (some properties may be methods)
                    try:
                        if callable(v):
                            v = v()
                    except Exception:
                        pass
                    return v
            except Exception:
                continue
        return None

    def _extract_metrics(info_obj, status_obj):
        # total seeds and connected nodes (best-effort)
        total_seeds = _safe_get(status_obj, 'num_seeds', 'num_complete')
        total_connected = _safe_get(status_obj, 'num_peers', 'num_connections')

        # trackers from torrent_info if available
        trackers = None
        try:
            if info_obj is not None:
                # torrent_info.trackers() may return a list of tracker_entry
                tlist = _safe_get(info_obj, 'trackers')
                if callable(tlist):
                    try:
                        tlist = tlist()
                    except Exception:
                        pass
                if isinstance(tlist, (list, tuple)):
                    # try to extract `url` attribute if present
                    trackers = []
                    for te in tlist:
                        try:
                            if hasattr(te, 'url'):
                                trackers.append(str(getattr(te, 'url')))
                            else:
                                trackers.append(str(te))
                        except Exception:
                            trackers.append(str(te))
        except Exception:
            trackers = None

        trackers_count = len(trackers) if isinstance(
            trackers, (list, tuple)) else None

        # info hash (best-effort)
        info_hash = None
        try:
            if info_obj is not None and hasattr(info_obj, 'info_hash'):
                ih = info_obj.info_hash()
                try:
                    # sha1_hash objects often have to_string()
                    info_hash = ih.to_string()
                except Exception:
                    info_hash = str(ih)
        except Exception:
            info_hash = None

        # loss / redownloads (best-effort from available attributes)
        total_failed_bytes = _safe_get(
            status_obj, 'total_failed_bytes', 'total_failed')
        total_redundant_bytes = _safe_get(
            status_obj, 'total_redundant_bytes', 'total_redundant')
        total_done = _safe_get(status_obj, 'total_done', 'total_wanted_done')

        loss = None
        if total_failed_bytes is not None and total_done is not None:
            try:
                denom = float(total_failed_bytes) + float(total_done)
                loss = float(total_failed_bytes) / denom if denom > 0 else 0.0
            except Exception:
                loss = None

        redownloads = None
        if total_redundant_bytes is not None:
            try:
                redownloads = int(total_redundant_bytes)
            except Exception:
                redownloads = None

        return {
            'total_seeds': total_seeds,
            'trackers': trackers,
            'trackers_count': trackers_count,
            'total_connected_nodes': total_connected,
            'info_hash': info_hash,
            'loss': loss,
            'redownloads': redownloads,
        }

    # monitoring loop

    sum_download_rate = 0
    download_count = 0
    sum_seeds = 0
    sum_peers = 0
    last_metrics = {}

    try:
        while not torrent_handle.status().is_seeding:
            # allow external cancellation
            if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                break

            status = torrent_handle.status()
            sum_download_rate += status.download_rate
            download_count += 1
            # aggregate seeds & peers for simple averages
            try:
                sum_seeds += int(getattr(status, 'num_seeds', 0) or 0)
            except Exception:
                pass
            try:
                sum_peers += int(getattr(status, 'num_peers', 0) or 0)
            except Exception:
                pass

            # extract extra metrics (best-effort)
            try:
                last_metrics = _extract_metrics(info, status)
            except Exception:
                last_metrics = {}

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

            # merge extracted metrics into status dict
            if last_metrics:
                status_dict.update(last_metrics)

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
        # aggregated averages and last-observed metrics
        'average_seeds': (sum_seeds / download_count) if download_count > 0 else None,
        'average_peers': (sum_peers / download_count) if download_count > 0 else None,
        'last_metrics': last_metrics,
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
                'run,total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes,average_seeds,average_peers,info_hash,trackers_count,loss,redownloads\n')
            for i, r in enumerate(all_results, start=1):
                lm = r.get('last_metrics', {}) if isinstance(r, dict) else {}
                fh.write(
                    f"{i},{r.get('total_time_seconds', 0)},{r.get('average_download_rate_kB_s', 0)},{r.get('total_downloaded_bytes', 0)},{r.get('average_seeds', '')},{r.get('average_peers', '')},{lm.get('info_hash', '')},{lm.get('trackers_count', '')},{lm.get('loss', '')},{lm.get('redownloads', '')}\n")
    except Exception as e:
        filepath = None
        print(f"Failed to write results file: {e}")

    return {'results': all_results, 'filename': filepath}


def download_torrent_full_parallel(progress_callback=None, stop_event=None):
    """Download the same torrent `RUN_TIMES` times in parallel using a single
    libtorrent session. Each run is saved into its own folder under `./downloads/run_<i>`.
    Returns a dict with per-run results and the CSV filepath (same columns as
    `download_torrent_for_results`).
    """
    import time as _time
    import os

    clear_downloads()

    session = lt.session()
    session.listen_on(6881, 6891)

    # apply parallel settings
    settings = get_settings_options(False)
    session.apply_settings(settings)

    info = lt.torrent_info(FILE_NAME)

    # prepare per-run folders and add torrent handles
    handles = []
    for i in range(1, RUN_TIMES + 1):
        save_path = os.path.join('downloads', f'run_{i}')
        os.makedirs(save_path, exist_ok=True)
        th = session.add_torrent({'ti': info, 'save_path': save_path})
        # ensure parallel (non-sequential) behavior
        try:
            th.set_sequential_download(False)
        except Exception:
            pass
        handles.append(th)

    # tracking arrays
    sum_download_rate = [0] * RUN_TIMES
    download_count = [0] * RUN_TIMES
    sum_seeds = [0] * RUN_TIMES
    sum_peers = [0] * RUN_TIMES
    last_metrics_list = [None] * RUN_TIMES
    finished = [False] * RUN_TIMES
    finish_time = [None] * RUN_TIMES
    total_done = [0] * RUN_TIMES

    start_time = datetime.now()

    try:
        # monitor until all handles are seeding
        while not all(finished):
            # allow external cancellation
            if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                break

            for idx, th in enumerate(handles):
                try:
                    status = th.status()
                except Exception:
                    # if a handle becomes invalid, mark finished and continue
                    if not finished[idx]:
                        finished[idx] = True
                        finish_time[idx] = (
                            datetime.now() - start_time).total_seconds()
                    continue

                if not finished[idx]:
                    sum_download_rate[idx] += status.download_rate
                    download_count[idx] += 1
                    try:
                        sum_seeds[idx] += int(getattr(status,
                                              'num_seeds', 0) or 0)
                    except Exception:
                        pass
                    try:
                        sum_peers[idx] += int(getattr(status,
                                              'num_peers', 0) or 0)
                    except Exception:
                        pass

                    # extract additional metrics (best-effort)
                    try:
                        def _safe_get(obj, *names):
                            for n in names:
                                try:
                                    if hasattr(obj, n):
                                        v = getattr(obj, n)
                                        try:
                                            if callable(v):
                                                v = v()
                                        except Exception:
                                            pass
                                        return v
                                except Exception:
                                    continue
                            return None

                        def _extract_metrics(info_obj, status_obj):
                            trackers = None
                            try:
                                tlist = _safe_get(info_obj, 'trackers')
                                if callable(tlist):
                                    try:
                                        tlist = tlist()
                                    except Exception:
                                        pass
                                if isinstance(tlist, (list, tuple)):
                                    trackers = []
                                    for te in tlist:
                                        try:
                                            if hasattr(te, 'url'):
                                                trackers.append(
                                                    str(getattr(te, 'url')))
                                            else:
                                                trackers.append(str(te))
                                        except Exception:
                                            trackers.append(str(te))
                            except Exception:
                                trackers = None

                            trackers_count = len(trackers) if isinstance(
                                trackers, (list, tuple)) else None

                            info_hash = None
                            try:
                                if info_obj is not None and hasattr(info_obj, 'info_hash'):
                                    ih = info_obj.info_hash()
                                    try:
                                        info_hash = ih.to_string()
                                    except Exception:
                                        info_hash = str(ih)
                            except Exception:
                                info_hash = None

                            total_failed_bytes = _safe_get(
                                status_obj, 'total_failed_bytes', 'total_failed')
                            total_redundant_bytes = _safe_get(
                                status_obj, 'total_redundant_bytes', 'total_redundant')
                            total_done = _safe_get(
                                status_obj, 'total_done', 'total_wanted_done')

                            loss = None
                            if total_failed_bytes is not None and total_done is not None:
                                try:
                                    denom = float(
                                        total_failed_bytes) + float(total_done)
                                    loss = float(total_failed_bytes) / \
                                        denom if denom > 0 else 0.0
                                except Exception:
                                    loss = None

                            redownloads = None
                            if total_redundant_bytes is not None:
                                try:
                                    redownloads = int(total_redundant_bytes)
                                except Exception:
                                    redownloads = None

                            return {
                                'trackers': trackers,
                                'trackers_count': trackers_count,
                                'info_hash': info_hash,
                                'loss': loss,
                                'redownloads': redownloads,
                            }

                        last_metrics_list[idx] = _extract_metrics(info, status)
                    except Exception:
                        last_metrics_list[idx] = last_metrics_list[idx] or {}

                    # if this handle finished, record finish time and total
                    if status.is_seeding:
                        finished[idx] = True
                        finish_time[idx] = (
                            datetime.now() - start_time).total_seconds()
                        total_done[idx] = status.total_done

                # emit per-run status for GUI consumers
                status_dict = {
                    'progress': status.progress,
                    'download_rate': status.download_rate,
                    'num_peers': status.num_peers,
                    'num_seeds': status.num_seeds,
                    'state': str(status.state),
                    'total_done': status.total_done,
                    'total_time': (datetime.now() - start_time).total_seconds(),
                }
                if progress_callback is not None:
                    try:
                        progress_callback(
                            {'type': 'status', 'data': status_dict, 'run': idx + 1})
                    except Exception:
                        pass

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nAborted.")

    # when loop exits, compute overall finish time (wall-clock until all finished)
    if any(t is None for t in finish_time):
        # not all finished; use elapsed time
        all_finished_time = (datetime.now() - start_time).total_seconds()
    else:
        # all finished; the overall time is the max individual finish time
        all_finished_time = max(finish_time) if finish_time else (
            datetime.now() - start_time).total_seconds()

    # gather final per-run results
    results = []
    for i in range(RUN_TIMES):
        avg_rate = (sum_download_rate[i] / download_count[i]
                    ) / 1000 if download_count[i] > 0 else 0
        t_done = total_done[i]
        t_time = finish_time[i] if finish_time[i] is not None else (
            datetime.now() - start_time).total_seconds()
        lm = last_metrics_list[i] or {}
        results.append({'run': i + 1, 'total_time_seconds': t_time,
                        'average_download_rate_kB_s': avg_rate, 'total_downloaded_bytes': t_done,
                        'average_seeds': (sum_seeds[i] / download_count[i]) if download_count[i] > 0 else None,
                        'average_peers': (sum_peers[i] / download_count[i]) if download_count[i] > 0 else None,
                        'last_metrics': lm,
                        'all_finished_time_seconds': all_finished_time})

    # write results to CSV like the other helper, with an extra column for overall parallel finish time
    timestamp = int(_time.time())
    filename = f"{timestamp}_full_parallel.csv"
    results_dir = './results'
    try:
        os.makedirs(results_dir, exist_ok=True)
        filepath = os.path.join(results_dir, filename)
        with open(filepath, 'w') as fh:
            fh.write(
                'run,total_time_seconds,average_download_rate_kB_s,total_downloaded_bytes,average_seeds,average_peers,info_hash,trackers_count,loss,redownloads,all_finished_time_seconds\n')
            for r in results:
                lm = r.get('last_metrics', {}) if isinstance(r, dict) else {}
                fh.write(
                    f"{r['run']},{r['total_time_seconds']},{r['average_download_rate_kB_s']},{r['total_downloaded_bytes']},{r.get('average_seeds', '')},{r.get('average_peers', '')},{lm.get('info_hash', '')},{lm.get('trackers_count', '')},{lm.get('loss', '')},{lm.get('redownloads', '')},{r['all_finished_time_seconds']}\n")
    except Exception as e:
        filepath = None
        print(f"Failed to write results file: {e}")

    return {'results': results, 'filename': filepath, 'all_finished_time_seconds': all_finished_time}


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
    clear_downloads()
    input_mode = input(
        "Enter 'p' for parallel download or 's' for serial download, or 'fp' for full parallel download: ").strip().lower()
    if input_mode == 'p':
        download_torrent_for_results(serial=False)
    elif input_mode == 's':
        download_torrent_for_results(serial=True)
    elif input_mode == 'fp':
        download_torrent_full_parallel()
    else:
        print("Invalid input. Please enter 'p' or 's'.")
