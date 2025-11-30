# 📘 Configuration Guide for `process_media`

This project reads all settings from a **JSON configuration file** (`config.json`).  
The `config.default.json` file is only a template — copy it to `config.json` and edit values for your environment.

---

## 🔹 Section: `paths`

| Key                   | Description                                                                 |
|-----------------------|-----------------------------------------------------------------------------|
| `root_dir`            | The “inbox” directory where new files are staged for processing.            |
| `tv_dir`              | Destination directory for regular TV shows in Plex.                         |
| `ao_tv_dir`           | Destination directory for Adult Only TV shows in Plex.                      |
| `movie_dir`           | Destination directory for Movies in Plex.                                   |
| `ao_movie_dir`        | Destination directory for Adult Only Movies in Plex.                        |
| `csv_file_path`       | Path to the CSV file that defines rules for TV shows.                       |
| `failure_dir`         | Directory where failed conversions are moved.                               |
| `tmp_base_dir`        | Local disk path used for **temporary working directories** (faster I/O).    |
| `root_movie_subdirs`  | A list of subfolders under `root_dir` scanned as “movie inboxes.” Each object has `{ name: "foldername", adult_only: true/false }`. |

---

## 🔹 Section: `plex`

| Key         | Description                                                                 |
|-------------|-----------------------------------------------------------------------------|
| `scheme`    | Usually "http" or "https".                                                  |
| `ip`        | IP address of your Plex Media Server.                                       |
| `port`      | Port number Plex is listening on (default: 32400).                          |
| `token`     | Your Plex API token. Required to trigger library refreshes.                 |
| `sections`  | List of Plex library section IDs to refresh after conversions (e.g., [2,3,4]). |

The script builds refresh URLs like:  
`http://<ip>:<port>/library/sections/<section>/refresh?X-Plex-Token=<token>`

---

## 🔹 Section: `encode`

| Key                 | Description                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| `preset_default`    | Encoding speed/efficiency tradeoff (lower = slower, higher = faster).       |
| `timeout_seconds`   | Maximum allowed ffmpeg runtime before considering the job failed.           |
| `tv_crf_fallback`   | Default CRF (quality) value used for TV shows if none specified in CSV.     |
| `movie_crf_defaults`| Mapping of resolution → CRF for movies (e.g., "1080p": 30, "4k": 28).       |

---

## 🔹 Section: `temp`

| Key                      | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| `stale_tmp_age_seconds`  | Age (in seconds) after which old temp directories are auto-deleted.         |

---

## 🔹 Section: `retention`

| Key                       | Description                                                                 |
|---------------------------|-----------------------------------------------------------------------------|
| `failure_retention_days`  | How many days to keep files in `failure_dir` before purging them.           |
| `failure_warn_days_before`| List of days before deletion when warnings should be logged.                |

---

## 📝 Example Workflow

1. You drop a file into `root_dir`.  
2. If it matches a CSV rule, it’s processed as a TV episode → sent to `tv_dir` or `ao_tv_dir`.  
3. If it looks like a movie, it’s processed into `movie_dir` or `ao_movie_dir`.  
4. Failed files are moved to `failure_dir`.  
5. ffmpeg encoding happens in `tmp_base_dir` for performance, then the final file is copied to Plex.  
6. After successful processing, the script hits Plex’s refresh URLs for each `sections` ID.
