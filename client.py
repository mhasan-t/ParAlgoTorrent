import libtorrent as lt
import time
from constants import TORRENT_FILE_NAME as FILE_NAME


def download_torrent(settings):
    session = lt.session()
    # standard ports for BitTorrent internet traffic
    session.listen_on(6881, 6891)

    # apply provided settings
    session.apply_settings(settings)

    # add the torrent
    info = lt.torrent_info(FILE_NAME)
    torrent_handle = session.add_torrent(
        {'ti': info, 'save_path': './downloads'})
    print(f"Starting download: {info.name()}")

    # monitoring loop

    sum_download_rate = 0
    download_count = 0

    try:
        while not torrent_handle.status().is_seeding:
            status = torrent_handle.status()
            sum_download_rate += status.download_rate
            download_count += 1

            print(f'\r{status.progress * 100:.2f}% | '
                  f'Down: {status.download_rate / 1000:.1f} kB/s | '
                  f'Peers: {status.num_peers} | '
                  f'Seeds: {status.num_seeds} | '
                  f'State: {status.state} | ')
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nAborted.")

    print("\nDownload complete!")

    data = {
        'average_download_rate_kB_s': (sum_download_rate / download_count) / 1000 if download_count > 0 else 0,
        'total_downloaded_bytes': torrent_handle.status().total_done,
        'total_time_seconds': torrent_handle.status().total_time
    }
    print(
        f"Average Download Rate: {data['average_download_rate_kB_s']:.2f} kB/s")

    return data


def download_in_parallel():
    settings = {
        'enable_dht': True,
        'enable_upnp': True,
        'enable_natpmp': True,
    }
    download_torrent(settings)


def download_serially():
    settings = {
        # limit to 1 connection to prevent parallel downloading from multiple peers
        'connections_limit': 1,

        # disable pipelining: only 1 outstanding request at a time
        'max_out_request_queue': 1,
        'max_allowed_in_request_queue': 1,

        # set sequential download order
        'mixed_mode_algorithm': 0,
    }
    download_torrent(settings)


if __name__ == "__main__":
    input_mode = input(
        "Enter 'p' for parallel download or 's' for serial download: ").strip().lower()
    if input_mode == 'p':
        download_in_parallel()
    elif input_mode == 's':
        download_serially()
    else:
        print("Invalid input. Please enter 'p' or 's'.")
