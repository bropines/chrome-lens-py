# This is the first prototype of the Google Lens API reverse.
# It's simpler, and without a lot of garbage, which is suitable for your projects if you want to rewrite it into another language.
import asyncio
import io
import json
import logging
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

import httpx

# --- JSON Parsing Setup ---
try:
    import json5

    json_loader = json5.loads
    logging.info("Using json5 for parsing.")
except ImportError:
    json_loader = json.loads
    logging.info("json5 not found, using standard json module.")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Constants ---
LENS_UPLOAD_ENDPOINT = "https://lens.google.com/v3/upload"
LENS_METADATA_ENDPOINT = "https://lens.google.com/qfmetadata"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not-A.Brand";v="8", "Chromium";v="135", "Google Chrome";v="135"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Origin": "https://www.google.com",
    "Referer": "https://www.google.com/",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
}
COOKIE_FILE = "cookies_lens_test.json"

# --- Helper Functions ---


async def read_image_data(image_path):
    """Reads image data from file."""
    try:
        with open(image_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"Image not found: {image_path}")
        return None
    except Exception as e:
        logging.error(f"Error reading image {image_path}: {e}")
        return None


def extract_ids_from_url(url_string):
    """Extracts vsrid and lsessionid from URL."""
    try:
        parsed_url = urlparse(url_string)
        query_params = parse_qs(parsed_url.query)
        vsrid = query_params.get("vsrid", [None])[0]
        lsessionid = query_params.get("lsessionid", [None])[0]
        return vsrid, lsessionid
    except Exception as e:
        logging.error(f"Error extracting IDs from URL {url_string}: {e}")
        return None, None


async def save_cookies(cookies, cookie_file):
    """Saves cookies to JSON file."""
    try:
        cookies_dict = {}
        cookie_jar = getattr(cookies, "jar", cookies)
        if hasattr(cookie_jar, "items"):
            for name, value in cookie_jar.items():
                if isinstance(value, str):
                    cookies_dict[name] = value
        elif hasattr(cookie_jar, "__iter__"):
            for cookie in cookie_jar:
                if hasattr(cookie, "name") and hasattr(cookie, "value"):
                    cookies_dict[cookie.name] = cookie.value
        else:
            logging.warning(
                f"Could not determine how to iterate cookies object: {type(cookies)}"
            )
            return

        with open(cookie_file, "w") as f:
            json.dump(cookies_dict, f, indent=2)
        logging.debug(f"Cookies saved to {cookie_file}")
    except Exception as e:
        logging.error(f"Error saving cookies: {e}")


async def load_cookies(cookie_file):
    """Loads cookies from JSON file."""
    try:
        if os.path.exists(cookie_file):
            with open(cookie_file, "r") as f:
                cookies_dict = json.load(f)
                logging.debug(f"Cookies loaded from {cookie_file}")
                return cookies_dict
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logging.warning(
            f"Error loading cookies from {cookie_file}: {e}. Ignoring cookies."
        )
    except Exception as e:
        logging.warning(
            f"Unexpected error loading cookies from {cookie_file}: {e}. Ignoring cookies."
        )
    return {}


def adaptive_parse_text_and_language(metadata_json):
    """
    Adaptively parses JSON to extract language, text blocks, and word annotations.
    """
    language = None
    all_word_annotations = []
    reconstructed_blocks = []

    try:
        if not isinstance(metadata_json, list) or not metadata_json:
            logging.error(
                "Invalid JSON structure: metadata_json is not a non-empty list."
            )
            return None, [], []
        response_container = next(
            (
                item
                for item in metadata_json
                if isinstance(item, list)
                and item
                and item[0] == "fetch_query_formulation_metadata_response"
            ),
            None,
        )
        if response_container is None:
            logging.error(
                "Could not find 'fetch_query_formulation_metadata_response' container."
            )
            return None, [], []

        # --- Language Extraction ---
        try:
            if len(response_container) > 2 and isinstance(response_container[2], list):
                lang_section = response_container[2]
                language = next(
                    (
                        element
                        for element in lang_section
                        if isinstance(element, str) and len(element) == 2
                    ),
                    None,
                )
                if language:
                    logging.debug(f"Found language code: '{language}'")
        except (IndexError, TypeError, StopIteration):
            logging.warning("Could not find language code in expected structure.")

        # --- Text/Word Extraction ---
        segments_iterable = None
        possible_paths_to_segments_list = [
            lambda rc: rc[2][0][0][0],
            lambda rc: rc[1][0][0][0],
            lambda rc: rc[2][0][0],
        ]
        path_names = ["[2][0][0][0]", "[1][0][0][0]", "[2][0][0]"]

        for i, path_func in enumerate(possible_paths_to_segments_list):
            path_name = path_names[i]
            try:
                candidate_iterable = path_func(response_container)
                if (
                    isinstance(candidate_iterable, list)
                    and candidate_iterable
                    and isinstance(candidate_iterable[0], list)
                ):
                    try:
                        first_segment = candidate_iterable[0]
                        if len(first_segment) > 1 and isinstance(
                            first_segment[1], list
                        ):
                            if (
                                first_segment[1]
                                and isinstance(first_segment[1][0], list)
                                and len(first_segment[1][0]) > 0
                                and isinstance(first_segment[1][0][0], list)
                            ):
                                segments_iterable = candidate_iterable
                                logging.debug(
                                    f"Segments list identified at path ending with {path_name}"
                                )
                                break
                    except (IndexError, TypeError):
                        pass
            except (IndexError, TypeError):
                pass

        if segments_iterable is None:
            logging.error(
                f"Could not identify valid text segments list using paths {path_names}."
            )
            return language, [], []

        for segment_list in segments_iterable:
            current_block_word_annotations = []
            block_text_builder = io.StringIO()
            last_word_ends_with_space = False

            if not isinstance(segment_list, list):
                logging.warning(
                    f"Skipping segment: Expected list, got {type(segment_list)}."
                )
                continue

            try:
                if len(segment_list) > 1 and isinstance(segment_list[1], list):
                    word_groups_list = segment_list[1]

                    for group_count, word_group in enumerate(word_groups_list, 1):
                        try:
                            if (
                                isinstance(word_group, list)
                                and len(word_group) > 0
                                and isinstance(word_group[0], list)
                                and isinstance(word_group[0][0], list)
                            ):

                                word_list = word_group[0]

                                if (
                                    group_count > 1
                                    and block_text_builder.tell() > 0
                                    and not last_word_ends_with_space
                                ):
                                    block_text_builder.write(" ")
                                    last_word_ends_with_space = True

                                for word_info in word_list:
                                    try:
                                        if (
                                            isinstance(word_info, list)
                                            and len(word_info) > 3
                                            and isinstance(word_info[1], str)
                                            and isinstance(word_info[2], str)
                                            and isinstance(word_info[3], list)
                                            and word_info[3]
                                            and isinstance(word_info[3][0], list)
                                        ):

                                            text = word_info[1]
                                            space_indicator = word_info[2]
                                            bbox = word_info[3][0]

                                            current_block_word_annotations.append(
                                                {"text": text, "bbox": bbox}
                                            )

                                            block_text_builder.write(text)
                                            block_text_builder.write(space_indicator)
                                            last_word_ends_with_space = (
                                                space_indicator == " "
                                            )

                                    except (IndexError, TypeError):
                                        pass
                        except (IndexError, TypeError):
                            pass
                else:
                    logging.warning("Word groups list structure [1] not found/invalid.")
            except (IndexError, TypeError):
                logging.error("Error processing segment structure.")
            except Exception as e:
                logging.error(f"Unexpected error processing segment: {e}")

            reconstructed_text = block_text_builder.getvalue().rstrip(" ")
            block_text_builder.close()

            if reconstructed_text or current_block_word_annotations:
                reconstructed_blocks.append(reconstructed_text)
                all_word_annotations.extend(current_block_word_annotations)

    except Exception as e:
        logging.error(
            f"Critical error during adaptive text extraction: {e}", exc_info=True
        )
        return language, reconstructed_blocks, all_word_annotations

    logging.info(
        f"Adaptive parsing complete. Language: '{language}'. Text blocks found: {len(reconstructed_blocks)}. Total word annotations: {len(all_word_annotations)}."
    )
    return language, reconstructed_blocks, all_word_annotations


async def scan_image(image_path):
    """Scans image via Google Lens, extracts text, language, and coordinates."""
    logging.info(f"Starting image scan: {image_path}")
    image_data = await read_image_data(image_path)
    if not image_data:
        return None, "Failed to read image data"

    filename = os.path.basename(image_path)
    _, ext = os.path.splitext(filename.lower())
    content_type = "image/jpeg"
    if ext == ".png":
        content_type = "image/png"
    elif ext == ".webp":
        content_type = "image/webp"
    elif ext == ".gif":
        content_type = "image/gif"
    logging.debug(f"Using content type: {content_type}")

    files = {"encoded_image": (filename, image_data, content_type)}
    params_upload = {
        "hl": "ru",
        "re": "av",
        "vpw": "1903",
        "vph": "953",
        "ep": "gsbubb",
        "st": str(int(time.time() * 1000)),
    }

    loaded_cookies = await load_cookies(COOKIE_FILE)
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(
        cookies=loaded_cookies,
        follow_redirects=True,
        timeout=timeout,
        limits=limits,
        http2=True,
        verify=True,
    ) as client:
        try:
            # --- 1. Upload Image to Lens ---
            logging.debug(f"POST request to {LENS_UPLOAD_ENDPOINT}")
            response_upload = await client.post(
                LENS_UPLOAD_ENDPOINT, headers=HEADERS, files=files, params=params_upload
            )
            await save_cookies(client.cookies, COOKIE_FILE)
            response_upload.raise_for_status()

            final_url = str(response_upload.url)

            # --- 2. Extract Session IDs from URL ---
            vsrid, lsessionid = extract_ids_from_url(final_url)
            if not vsrid or not lsessionid:
                logging.error(
                    "Failed to extract vsrid or lsessionid from upload redirect URL."
                )
                return None, "Failed to get session IDs from upload response"

            # --- 3. Fetch Metadata from Lens ---
            metadata_params = {
                "vsrid": vsrid,
                "lsessionid": lsessionid,
                "hl": params_upload["hl"],
                "qf": "CAI%3D",
                "st": str(int(time.time() * 1000)),
                "vpw": params_upload["vpw"],
                "vph": params_upload["vph"],
                "source": "lens",
            }
            metadata_headers = HEADERS.copy()
            metadata_headers.update(
                {
                    "Accept": "*/*",
                    "Referer": final_url,
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                    "Priority": "u=1, i",
                }
            )
            metadata_headers.pop("Upgrade-Insecure-Requests", None)
            metadata_headers.pop("Sec-Fetch-User", None)
            metadata_headers.pop("Cache-Control", None)
            metadata_headers.pop("Origin", None)

            metadata_url_obj = httpx.URL(LENS_METADATA_ENDPOINT, params=metadata_params)
            logging.debug(f"GET request to {str(metadata_url_obj)}")
            response_metadata = await client.get(
                metadata_url_obj, headers=metadata_headers
            )
            await save_cookies(client.cookies, COOKIE_FILE)
            response_metadata.raise_for_status()

            # --- 4. Parse Metadata Response ---
            response_text = response_metadata.text
            if response_text.startswith(")]}'\n"):
                response_text = response_text[5:]
            elif response_text.startswith(")]}'"):
                response_text = response_text[4:]

            try:
                metadata_json = json_loader(response_text)

                # --- 5. Extract Data using Adaptive Parser ---
                language, reconstructed_blocks, all_word_annotations = (
                    adaptive_parse_text_and_language(metadata_json)
                )
                full_text = "\n".join(reconstructed_blocks)

                result_data = {
                    "text": full_text,
                    "language": language if language else "und",
                    "text_with_coordinates": json.dumps(
                        all_word_annotations, ensure_ascii=False
                    ),  # JSON as string
                }
                return result_data, metadata_json

            except Exception as e_parse:
                logging.error(
                    f"Error parsing JSON or extracting text: {e_parse}", exc_info=True
                )
                return None, response_metadata.text

        except httpx.HTTPStatusError as e:
            logging.error(
                f"HTTP error: {e.response.status_code} for URL {e.request.url}"
            )
            return None, f"HTTP Error {e.response.status_code}"
        except httpx.RequestError as e:
            logging.error(f"Request error: {e}")
            return None, f"Request Error: {e}"
        except Exception as e:
            logging.error(f"Unexpected error in scan_image: {e}", exc_info=True)
            return None, f"Unexpected Error: {e}"


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f"Error: File not found: {image_path}")
        sys.exit(1)

    print(f"Starting Google Lens scan for: {image_path}")
    start_total_time = time.time()

    result_dict, raw_data = await scan_image(image_path)

    end_total_time = time.time()
    logging.info(
        f"Total scan_image execution time: {end_total_time - start_total_time:.2f} sec."
    )

    if result_dict:
        print("\n--- Google Lens Scan Result ---")
        print(
            json.dumps(result_dict, indent=2, ensure_ascii=False)
        )  # Output result as JSON
        print("------------------------------")
    else:
        print("\nGoogle Lens scan failed.")
        logging.error(f"Scan failed. Details: {raw_data}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
