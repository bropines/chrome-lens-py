import asyncio
import io
import json
import logging
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

import httpx

try:
    import json5

    json_loader = json5.loads
except ImportError:
    json_loader = json.loads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
main_log = logging.getLogger("main")
scan_log = logging.getLogger("scan_image")
http_log = logging.getLogger("http_client")
parse_log = logging.getLogger("parser")
cookie_log = logging.getLogger("cookies")
io_log = logging.getLogger("image_io")


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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Client-Data": "CIW2yQEIorbJAQipncoBCIH+ygEIkqHLAQiKo8sBCPWYzQEIhaDNAQji0M4BCLPTzgEI19TOAQjy1c4BCJLYzgEIwNjOAQjM2M4BGM7VzgE=",
    "Origin": "https://www.google.com",
    "Referer": "https://www.google.com/",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
COOKIE_FILE = "cookies_lens_test.json"


async def read_image_data(image_path):
    """Reads image data from file."""
    io_log.debug(f"Attempting to read image: {image_path}")
    start_time = time.perf_counter()
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        end_time = time.perf_counter()
        io_log.debug(
            f"Read {len(data)} bytes from {image_path} in {end_time - start_time:.4f} sec."
        )
        return data
    except FileNotFoundError:
        io_log.error(f"Image not found: {image_path}")
        return None
    except Exception as e:
        io_log.error(f"Error reading image {image_path}: {e}", exc_info=True)
        return None


def extract_ids_from_url(url_string):
    """Extracts vsrid and lsessionid from URL."""
    parse_log.debug(f"Attempting to extract IDs from URL: {url_string}")
    start_time = time.perf_counter()
    try:
        parsed_url = urlparse(url_string)
        query_params = parse_qs(parsed_url.query)
        vsrid = query_params.get("vsrid", [None])[0]
        lsessionid = query_params.get("lsessionid", [None])[0]
        end_time = time.perf_counter()
        if vsrid and lsessionid:
            parse_log.debug(
                f"Extracted vsrid='{vsrid}', lsessionid='{lsessionid}' in {end_time - start_time:.4f} sec."
            )
        else:
            parse_log.warning(
                f"Could not extract vsrid or lsessionid from URL in {end_time - start_time:.4f} sec."
            )
        return vsrid, lsessionid
    except Exception as e:
        parse_log.error(
            f"Error extracting IDs from URL {url_string}: {e}", exc_info=True
        )
        return None, None


async def save_cookies(cookies, cookie_file):
    """Saves cookies to JSON file."""
    cookie_log.debug(f"Attempting to save cookies to {cookie_file}")
    start_time = time.perf_counter()
    try:
        cookies_dict = {}
        cookie_jar = getattr(cookies, "jar", cookies)
        if hasattr(cookie_jar, "items"):
            for name, value in cookie_jar.items():
                cookie_obj = cookie_jar.get(name)
                if cookie_obj and hasattr(cookie_obj, "value"):
                    cookies_dict[name] = cookie_obj.value
                elif isinstance(value, str):
                    cookies_dict[name] = value
        elif hasattr(cookie_jar, "__iter__"):
            for cookie in cookie_jar:
                if hasattr(cookie, "name") and hasattr(cookie, "value"):
                    cookies_dict[cookie.name] = cookie.value
        else:
            cookie_log.warning(
                f"Could not determine how to iterate cookies object: {type(cookies)}"
            )
            return

        with open(cookie_file, "w") as f:
            json.dump(cookies_dict, f, indent=2)
        end_time = time.perf_counter()
        cookie_log.debug(
            f"Cookies saved ({len(cookies_dict)} items) to {cookie_file} in {end_time - start_time:.4f} sec."
        )
    except Exception as e:
        cookie_log.error(f"Error saving cookies: {e}", exc_info=True)


async def load_cookies(cookie_file):
    """Loads cookies from JSON file."""
    cookie_log.debug(f"Attempting to load cookies from {cookie_file}")
    start_time = time.perf_counter()
    try:
        if os.path.exists(cookie_file):
            with open(cookie_file, "r") as f:
                cookies_dict = json.load(f)
                end_time = time.perf_counter()
                cookie_log.debug(
                    f"Cookies loaded ({len(cookies_dict)} items) from {cookie_file} in {end_time - start_time:.4f} sec."
                )
                return cookies_dict
        else:
            cookie_log.debug(f"Cookie file {cookie_file} not found.")
            return {}
    except (json.JSONDecodeError, FileNotFoundError) as e:
        cookie_log.warning(
            f"Error loading cookies from {cookie_file}: {e}. Ignoring cookies."
        )
    except Exception as e:
        cookie_log.warning(
            f"Unexpected error loading cookies from {cookie_file}: {e}. Ignoring cookies."
        )
    return {}


def adaptive_parse_text_and_language(metadata_json):
    """
    Adaptively parses JSON to extract language, text blocks, and word annotations.
    """
    parse_log.info("Starting adaptive parsing of metadata JSON.")
    start_time = time.perf_counter()
    language = None
    all_word_annotations = []
    reconstructed_blocks = []

    try:
        if not isinstance(metadata_json, list) or not metadata_json:
            parse_log.error(
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
            parse_log.error(
                "Could not find 'fetch_query_formulation_metadata_response' container."
            )
            return None, [], []
        parse_log.debug("'fetch_query_formulation_metadata_response' container found.")

        lang_start_time = time.perf_counter()
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
                    parse_log.debug(
                        f"Found potential language code: '{language}' in {time.perf_counter() - lang_start_time:.4f} sec."
                    )
                else:
                    parse_log.debug(
                        f"No direct 2-char language code found in section [2] in {time.perf_counter() - lang_start_time:.4f} sec."
                    )
            else:
                parse_log.debug(
                    f"Language section [2] not found or not a list in {time.perf_counter() - lang_start_time:.4f} sec."
                )

        except (IndexError, TypeError, StopIteration):
            parse_log.warning(
                "Could not find language code using primary method.", exc_info=True
            )

        parse_log.debug("Searching for text segments list...")
        segments_iterable = None
        possible_paths_to_segments_list = [
            lambda rc: rc[2][0][0][0],
            lambda rc: rc[1][0][0][0],
            lambda rc: rc[2][0][0],
        ]
        path_names = ["[2][0][0][0]", "[1][0][0][0]", "[2][0][0]"]
        path_search_start = time.perf_counter()

        for i, path_func in enumerate(possible_paths_to_segments_list):
            path_name = path_names[i]
            parse_log.debug(f"Trying path ending with {path_name}...")
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
                                parse_log.debug(
                                    f"Segments list identified at path ending with {path_name}."
                                )
                                break
                    except (IndexError, TypeError) as e_check:
                        parse_log.debug(
                            f"Path {path_name} candidate structure check failed: {e_check}"
                        )
                        pass
            except (IndexError, TypeError) as e_path:
                parse_log.debug(f"Path {path_name} access failed: {e_path}")
                pass

        parse_log.debug(
            f"Path search finished in {time.perf_counter() - path_search_start:.4f} sec."
        )

        if segments_iterable is None:
            parse_log.error(
                f"Could not identify valid text segments list using known paths {path_names}. Full structure might have changed."
            )
            return language, [], []

        parse_log.info(
            f"Processing {len(segments_iterable)} potential text segments..."
        )
        # segment_processing_start = time.perf_counter()

        for i, segment_list in enumerate(segments_iterable):
            segment_start_time = time.perf_counter()
            current_block_word_annotations = []
            block_text_builder = io.StringIO()
            last_word_ends_with_space = False

            if not isinstance(segment_list, list):
                parse_log.warning(
                    f"Skipping segment #{i}: Expected list, got {type(segment_list)}."
                )
                continue

            try:
                if len(segment_list) > 1 and isinstance(segment_list[1], list):
                    word_groups_list = segment_list[1]
                    parse_log.debug(
                        f"Segment #{i}: Found {len(word_groups_list)} word groups."
                    )

                    for group_count, word_group in enumerate(word_groups_list, 1):
                        try:
                            if (
                                isinstance(word_group, list)
                                and len(word_group) > 0
                                and isinstance(word_group[0], list)
                            ):

                                word_list = word_group[0]
                                parse_log.debug(
                                    f"  Group {group_count}: Found {len(word_list)} words."
                                )

                                if (
                                    group_count > 1
                                    and block_text_builder.tell() > 0
                                    and not last_word_ends_with_space
                                ):
                                    block_text_builder.write(" ")
                                    last_word_ends_with_space = True

                                for word_idx, word_info in enumerate(word_list):
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
                                            if space_indicator == " ":
                                                block_text_builder.write(
                                                    space_indicator
                                                )
                                                last_word_ends_with_space = True
                                            else:
                                                last_word_ends_with_space = False
                                        else:
                                            parse_log.warning(
                                                f"Segment #{i}, Group {group_count}, Word {word_idx}: Unexpected word_info structure or type: {word_info}"
                                            )

                                    except (IndexError, TypeError) as e_word:
                                        parse_log.warning(
                                            f"Segment #{i}, Group {group_count}, Word {word_idx}: Error processing word_info: {e_word}. Data: {word_info}"
                                        )
                                        pass
                            else:
                                parse_log.warning(
                                    f"Segment #{i}, Group {group_count}: Unexpected word_group structure: {word_group}"
                                )

                        except (IndexError, TypeError) as e_group:
                            parse_log.warning(
                                f"Segment #{i}, Group {group_count}: Error processing word_group: {e_group}. Data: {word_group}"
                            )
                            pass
                else:
                    parse_log.warning(
                        f"Segment #{i}: Word groups list structure segment_list[1] not found or invalid. Segment data: {segment_list}"
                    )
            except (IndexError, TypeError) as e_segment:
                parse_log.error(
                    f"Segment #{i}: Error processing segment structure: {e_segment}. Data: {segment_list}",
                    exc_info=True,
                )
            except Exception as e_segment_unexpected:
                parse_log.error(
                    f"Segment #{i}: Unexpected error processing segment: {e_segment_unexpected}",
                    exc_info=True,
                )

            reconstructed_text = (
                block_text_builder.getvalue().rstrip(" ")
                if not last_word_ends_with_space
                else block_text_builder.getvalue()
            )
            block_text_builder.close()

            segment_end_time = time.perf_counter()
            parse_log.debug(
                f"Segment #{i} processed in {segment_end_time - segment_start_time:.4f} sec. Text length: {len(reconstructed_text)}, Annotations: {len(current_block_word_annotations)}"
            )

            if reconstructed_text or current_block_word_annotations:
                reconstructed_blocks.append(reconstructed_text)
                all_word_annotations.extend(current_block_word_annotations)
            else:
                parse_log.debug(f"Segment #{i} resulted in no text or annotations.")

    except Exception as e:
        parse_log.error(
            f"Critical error during adaptive text extraction: {e}", exc_info=True
        )
        return language, reconstructed_blocks, all_word_annotations

    total_parse_time = time.perf_counter() - start_time
    parse_log.info(
        f"Adaptive parsing finished in {total_parse_time:.4f} sec. Language: '{language}'. Text blocks: {len(reconstructed_blocks)}. Word annotations: {len(all_word_annotations)}."
    )
    return language, reconstructed_blocks, all_word_annotations


async def scan_image(image_path):
    """Scans image via Google Lens, extracts text, language, and coordinates."""
    scan_log.info(f"Starting image scan process for: {image_path}")
    total_scan_start_time = time.perf_counter()

    read_start = time.perf_counter()
    image_data = await read_image_data(image_path)
    read_end = time.perf_counter()
    scan_log.info(f"Image read finished in {read_end - read_start:.4f} sec.")
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
    scan_log.debug(f"Determined filename: '{filename}', content type: {content_type}")

    files = {"encoded_image": (filename, image_data, content_type)}
    params_upload = {
        "hl": "ru",
        "re": "av",
        "vpw": "1903",
        "vph": "953",
        "ep": "gsbubb",
        "st": str(int(time.time() * 1000)),
    }

    cookie_load_start = time.perf_counter()
    loaded_cookies = await load_cookies(COOKIE_FILE)
    cookie_load_end = time.perf_counter()
    scan_log.info(
        f"Cookie loading finished in {cookie_load_end - cookie_load_start:.4f} sec."
    )

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(60.0, connect=15.0)
    http_log.debug(f"Configuring httpx client: timeout={timeout}, limits={limits}")

    async with httpx.AsyncClient(
        cookies=loaded_cookies,
        follow_redirects=True,
        timeout=timeout,
        limits=limits,
        http2=True,
        verify=True,
    ) as client:
        try:
            http_log.info(f"POST request initiated to {LENS_UPLOAD_ENDPOINT}")
            upload_start_time = time.perf_counter()
            response_upload = await client.post(
                LENS_UPLOAD_ENDPOINT, headers=HEADERS, files=files, params=params_upload
            )
            upload_end_time = time.perf_counter()
            http_log.info(
                f"POST request to {LENS_UPLOAD_ENDPOINT} finished in {upload_end_time - upload_start_time:.4f} sec. "
                f"Status: {response_upload.status_code}. Final URL: {response_upload.url}"
            )

            cookie_save_start = time.perf_counter()
            await save_cookies(client.cookies, COOKIE_FILE)
            cookie_save_end = time.perf_counter()
            http_log.debug(
                f"Cookies saved after upload in {cookie_save_end - cookie_save_start:.4f} sec."
            )

            response_upload.raise_for_status()

            final_url = str(response_upload.url)

            extract_start = time.perf_counter()
            vsrid, lsessionid = extract_ids_from_url(final_url)
            extract_end = time.perf_counter()
            scan_log.info(
                f"ID extraction finished in {extract_end - extract_start:.4f} sec."
            )
            if not vsrid or not lsessionid:
                scan_log.error(
                    "Failed to extract vsrid or lsessionid from upload redirect URL."
                )
                return None, f"Failed to get session IDs from URL: {final_url}"

            scan_log.info("Waiting for 1 second before metadata request...")
            await asyncio.sleep(1)
            scan_log.info("Wait finished. Proceeding with metadata request.")

            metadata_params = {
                "vsrid": vsrid,
                "lsessionid": lsessionid,
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
            metadata_url_str = str(metadata_url_obj)
            http_log.info(
                f"GET request initiated to {LENS_METADATA_ENDPOINT} (URL: {metadata_url_str})"
            )
            http_log.debug(f"Metadata request headers: {metadata_headers}")
            metadata_start_time = time.perf_counter()

            response_metadata = await client.get(
                metadata_url_obj, headers=metadata_headers
            )
            metadata_end_time = time.perf_counter()
            http_log.info(
                f"GET request to {LENS_METADATA_ENDPOINT} finished in {metadata_end_time - metadata_start_time:.4f} sec. "
                f"Status: {response_metadata.status_code}"
            )

            cookie_save_start = time.perf_counter()
            await save_cookies(client.cookies, COOKIE_FILE)
            cookie_save_end = time.perf_counter()
            http_log.debug(
                f"Cookies saved after metadata fetch in {cookie_save_end - cookie_save_start:.4f} sec."
            )

            response_metadata.raise_for_status()

            parse_log.info("Starting metadata response processing.")
            process_start_time = time.perf_counter()

            response_text = response_metadata.text
            original_len = len(response_text)
            if response_text.startswith(")]}'\n"):
                response_text = response_text[5:]
                parse_log.debug("Removed ')]}'\\n prefix")
            elif response_text.startswith(")]}'"):
                response_text = response_text[4:]
                parse_log.debug("Removed ')]}' prefix")
            stripped_len = len(response_text)
            parse_log.debug(f"Response text length: {original_len} -> {stripped_len}")

            try:
                json_parse_start = time.perf_counter()
                metadata_json = json_loader(response_text)
                json_parse_end = time.perf_counter()
                parse_log.info(
                    f"JSON parsing finished in {json_parse_end - json_parse_start:.4f} sec."
                )

                # extract_start_time = time.perf_counter()
                language, reconstructed_blocks, all_word_annotations = (
                    adaptive_parse_text_and_language(metadata_json)
                )
                # extract_end_time = time.perf_counter()

                full_text = "\n".join(reconstructed_blocks)

                result_data = {
                    "text": full_text,
                    "language": language if language else "und",
                    "text_with_coordinates": json.dumps(
                        all_word_annotations, ensure_ascii=False, indent=None
                    ),
                }
                process_end_time = time.perf_counter()
                parse_log.info(
                    f"Total metadata processing (strip + JSON parse + adaptive extract) finished in {process_end_time - process_start_time:.4f} sec."
                )

                total_scan_end_time = time.perf_counter()
                scan_log.info(
                    f"Image scan process completed successfully in {total_scan_end_time - total_scan_start_time:.4f} sec."
                )
                return result_data, metadata_json

            except Exception as e_parse:
                parse_log.error(
                    f"Error parsing JSON or extracting text: {e_parse}", exc_info=True
                )
                log_snippet = (
                    response_text[:500] + "..."
                    if len(response_text) > 500
                    else response_text
                )
                parse_log.error(f"Problematic text snippet (start): {log_snippet}")
                total_scan_end_time = time.perf_counter()
                scan_log.error(
                    f"Image scan process failed during parsing/extraction after {total_scan_end_time - total_scan_start_time:.4f} sec."
                )
                return None, response_metadata.text

        except httpx.HTTPStatusError as e:
            http_log.error(
                f"HTTP error: {e.response.status_code} for URL {e.request.url}",
                exc_info=True,
            )
            try:
                body_snippet = (
                    e.response.text[:500] + "..."
                    if len(e.response.text) > 500
                    else e.response.text
                )
                http_log.error(f"Response body snippet: {body_snippet}")
            except Exception:
                http_log.error("Could not read response body.")
            total_scan_end_time = time.perf_counter()
            scan_log.error(
                f"Image scan process failed due to HTTP error after {total_scan_end_time - total_scan_start_time:.4f} sec."
            )
            return None, f"HTTP Error {e.response.status_code}: {e.request.url}"
        except httpx.RequestError as e:
            http_log.error(f"Request error for URL {e.request.url}: {e}", exc_info=True)
            total_scan_end_time = time.perf_counter()
            scan_log.error(
                f"Image scan process failed due to request error after {total_scan_end_time - total_scan_start_time:.4f} sec."
            )
            return None, f"Request Error: {e}"
        except Exception as e:
            scan_log.error(f"Unexpected error in scan_image: {e}", exc_info=True)
            total_scan_end_time = time.perf_counter()
            scan_log.error(
                f"Image scan process failed unexpectedly after {total_scan_end_time - total_scan_start_time:.4f} sec."
            )
            return None, f"Unexpected Error: {e}"


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        main_log.error(f"Error: File not found: {image_path}")
        sys.exit(1)

    main_log.info("========================================")
    main_log.info(f"Starting Google Lens scan for: {image_path}")
    main_log.info(
        f"Using log level: {logging.getLevelName(logging.getLogger().getEffectiveLevel())}"
    )
    main_log.info("========================================")
    start_total_time = time.perf_counter()

    result_dict, raw_data_or_error = await scan_image(image_path)

    end_total_time = time.perf_counter()
    main_log.info(
        f"--- Total execution time for scan_image call: {end_total_time - start_total_time:.4f} sec. ---"
    )

    if result_dict:
        print("\n--- Google Lens Scan Result ---")
        try:
            print(f"Language: {result_dict.get('language', 'N/A')}")
            print("\nText:")
            print(result_dict.get("text", "N/A"))
            print("\nText with Coordinates (JSON String):")
            coords_json_str = result_dict.get("text_with_coordinates", "[]")
            try:
                coords_data = json.loads(coords_json_str)
                print(json.dumps(coords_data, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(coords_json_str)
            print("------------------------------")
            main_log.info("Scan successful. Results printed.")
        except Exception as e:
            main_log.error(f"Error printing results: {e}")
            print("\n--- Raw Result Dictionary ---")
            print(result_dict)
    else:
        print("\nGoogle Lens scan failed.")
        main_log.error(
            f"Scan failed. See previous logs for details. Error context/data: {raw_data_or_error}"
        )


if __name__ == "__main__":
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    elif sys.platform == "win32":
        pass

    asyncio.run(main())
