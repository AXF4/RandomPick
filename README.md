<div align="center">

# Randompick

**A feature-rich Discord bot designed to search, bookmark, and manage random images seamlessly using custom tags.**

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/Discord.py-API-5865F2.svg)](https://discord.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)

</div>

# 1. Overview
* **Project Name:** Randompick
* **Description:** A feature-rich Discord bot designed to search, bookmark, and manage random images seamlessly using custom tags.
* **Screenshots:**
  <p align="center">
    <img width="700" alt="Randompic feature screenshot 1" src="https://github.com/user-attachments/assets/60e242e6-37e3-4b60-a861-91f783875881" />
    <br>
    <img width="700" alt="Randompic feature screenshot 2" src="https://github.com/user-attachments/assets/b45766c9-844c-4194-a97e-77e9777c4550" />
  </p>

# 2. Tech Stack
* **Language:** Python
* **Database:** SQLite
* **External API:** Safebooru API

# 3. Key Features
* **Tag-based Random Image Search:** Users can fetch random images matching specific tags using the `randompic` command (supports multi-tags, auto-completion, and tag hints).
* **Interactive UI:** Provides interactive buttons (`OneMore`, `Bookmark`, `Info`, `Delete`) for an enhanced user experience.
* **User Settings:** Allows users to configure preferences such as AI illustration display settings via the `setting` command.

# 4. Troubleshooting
* **Securing API Keys and Sensitive Data (v1.5.2)**
  * **Issue:** Risk of hardcoded API keys or sensitive credentials being exposed in the repository.
  * **Solution:** Refactored configuration handling to load environment variables securely using `.env` files, preventing accidental exposure in source control.
* **Preserving Button State After Bot Restarts (v1.9.0)**
  * **Issue:** Interactive UI buttons (`info`, `onemore`) became unresponsive when the bot restarted.
  * **Solution:** Restructured how persistent view states and message identifiers are tracked, ensuring component callbacks remain functional even after service restarts.
* **403 Forbidden During Autocomplete feature (v2.0.0)**
  * **Issue:** Autocomplete feature can cause 403 Forbidden Error because of a lot of requests.
  * **Solution:** Made Global and Individual Cooldown

# 5. Update Log
* Check out the detailed version history in the [Changelog](https://github.com/AXF4/RandomPick/blob/main/Changelog.md).

# 6. Getting Started
1. clone repository
```bash
git clone https://github.com/AXF4/RandomPick.git
```
2. Install Dependencies
```bash
pip install -r requirements.txt
```
3. Set up environment variables `(.env)`
```
TOKEN=YOUR_TOKEN_HERE
DEVID=YOUR_DISCORD_USER_ID_HERE
```
4. Run the Bot
```bash
python bot.py
```
* **Database Note:** The `settings.db` file is ignored by Git for security and will be automatically created upon the first run of the bot.
