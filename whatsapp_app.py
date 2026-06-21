from __future__ import annotations

from pathlib import Path
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait


def _clean_phone_number(phone_number: str) -> str:
    """Keep only digits from the phone number."""
    cleaned = "".join(char for char in phone_number if char.isdigit())
    if not cleaned:
        raise ValueError("Phone number is empty or invalid.")
    return cleaned


def _collect_files(folder_path: str) -> list[Path]:
    """Collect all files directly inside the selected folder."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Path is not a folder: {folder}")

    files = sorted(path for path in folder.iterdir() if path.is_file())
    if not files:
        raise ValueError(f"No files found in folder: {folder}")
    return files


def _create_driver() -> webdriver.Chrome:
    """
    Create Chrome driver with a persistent local profile.

    This keeps WhatsApp Web login session between runs.
    """
    profile_dir = Path(__file__).resolve().parent / ".whatsapp_chrome_profile"
    profile_dir.mkdir(exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--log-level=3")

    return webdriver.Chrome(options=options)


def _open_attachment_menu(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """Open chat attachment menu in a locale-independent way."""
    attach_locators = [
        (By.CSS_SELECTOR, "span[data-icon='clip']"),
        (By.CSS_SELECTOR, "button[title='Attach']"),
    ]
    for locator in attach_locators:
        elements = driver.find_elements(*locator)
        for element in elements:
            try:
                if element.is_displayed():
                    ActionChains(driver).move_to_element(element).click().perform()
                    return
            except Exception:
                continue
    raise TimeoutException("Could not find attachment button.")


def _upload_file(driver: webdriver.Chrome, wait: WebDriverWait, file_path: Path) -> None:
    """Upload one file into WhatsApp attachment dialog."""
    _open_attachment_menu(driver, wait)

    # Prefer document input first (works for most file types),
    # fallback to any available file input.
    input_locators = [
        (By.CSS_SELECTOR, "input[type='file'][accept='*']"),
        (By.CSS_SELECTOR, "input[type='file']"),
    ]
    for locator in input_locators:
        inputs = driver.find_elements(*locator)
        for input_element in inputs:
            try:
                input_element.send_keys(str(file_path.resolve()))
                return
            except Exception:
                continue
    raise TimeoutException("Could not upload file to any input element.")


def _click_send_button(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """Click the attachment send button after upload preview appears."""
    send_locators = [
        (By.CSS_SELECTOR, "button[aria-label='Send']"),
        (By.CSS_SELECTOR, "span[data-icon='send']"),
    ]
    for locator in send_locators:
        elements = driver.find_elements(*locator)
        for element in reversed(elements):
            try:
                if element.is_displayed() and element.is_enabled():
                    ActionChains(driver).move_to_element(element).click().perform()
                    return
            except Exception:
                continue
    raise TimeoutException("Could not find clickable send button.")


def send_files_to_whatsapp(phone_number: str, folder_path: str, timeout_seconds: int = 300) -> None:
    """
    Open WhatsApp Web and send all files in a folder to one number.

    User must scan WhatsApp QR code when prompted if not already logged in.
    """
    target_phone = _clean_phone_number(phone_number)
    files = _collect_files(folder_path)

    driver = _create_driver()
    wait = WebDriverWait(driver, timeout_seconds)
    per_file_wait = WebDriverWait(driver, 30)

    try:
        url = f"https://web.whatsapp.com/send?phone={target_phone}"
        driver.get(url)

        print("Waiting for WhatsApp Web to load...")
        print("If needed, scan QR code in the browser.")
        print("When chat is fully open, return here and press Enter.")
        input("Press Enter to continue sending files...")

        time.sleep(2)

        for idx, file_path in enumerate(files, start=1):
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"[{idx}/{len(files)}] Uploading: {file_path.name} ({file_size_mb:.2f} MB)")

            _upload_file(driver, per_file_wait, file_path)
            # Give upload preview a short moment to render.
            time.sleep(1)
            _click_send_button(driver, per_file_wait)
            print(f"[{idx}/{len(files)}] Sent: {file_path.name}")
            time.sleep(0.8)

        print(f"Done. Sent {len(files)} file(s) to {target_phone}.")

    except TimeoutException as exc:
        raise TimeoutError(
            "Timed out waiting for WhatsApp Web elements. "
            "Check internet connection or login state."
        ) from exc
    finally:
        input("Press Enter to close browser...")
        driver.quit()


def main() -> None:
    print("=== WhatsApp Folder Sender ===")
    phone_number = input("Enter WhatsApp number with country code (example: 201234567890): ").strip()
    folder_path = input("Enter folder path containing files to send: ").strip()

    try:
        send_files_to_whatsapp(phone_number=phone_number, folder_path=folder_path)
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
