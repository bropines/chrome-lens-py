# import json  # To potentially parse the coordinate string if needed elsewhere
import logging

# import math  # For degrees conversion
import re

# Note: Stitching logic needs significant changes due to the new bbox format.
# The old methods relied heavily on simple [y, x] sorting.
# We'll adapt stitch_text_sequential and provide a simplified smart stitch.


def stitch_text_sequential(word_annotations):
    """Stitches text sequentially based on the order of word annotations."""
    if not word_annotations:
        return ""
    # Assumes word_annotations is the list of {"text": "word", "bbox": [...], ...} dicts
    texts = [item.get("text", "") for item in word_annotations]
    # Basic joining, might need smarter space handling based on original script's logic if available
    stitched_text = " ".join(texts)
    # Simple punctuation cleanup (can be improved)
    stitched_text = re.sub(r"\s+([,.!?;:])", r"\1", stitched_text)
    stitched_text = re.sub(
        r'([«“"\'])\s+', r"\1", stitched_text
    )  # Fix space after opening quote
    stitched_text = re.sub(
        r'\s+([»”"\'])', r"\1", stitched_text
    )  # Fix space before closing quote
    return stitched_text.strip()


def stitch_text_smart(word_annotations):
    """
    Stitches text attempting to reconstruct lines based on bounding box vertical positions.
    Simplified approach using bbox center y for sorting.
    """
    if not word_annotations:
        return ""

    # Extract relevant info: text, center y (bbox[0]), center x (bbox[1])
    elements = []
    for item in word_annotations:
        text = item.get("text")
        bbox = item.get("bbox")
        if text and isinstance(bbox, list) and len(bbox) >= 2:
            # Use center Y (index 0) and center X (index 1) from bbox
            elements.append({"text": text, "y": bbox[0], "x": bbox[1]})
        elif text:
            # Fallback if bbox is malformed - add without coords, will be appended at end
            elements.append({"text": text, "y": float("inf"), "x": float("inf")})

    # Sort primarily by approximate vertical position (y), then horizontal (x)
    # Round y slightly to group words on the same visual line
    # Threshold for y-grouping might need tuning
    y_grouping_threshold = (
        0.01  # Relative threshold (adjust based on image size/resolution if needed)
    )
    sorted_elements = sorted(
        elements, key=lambda e: (round(e["y"] / y_grouping_threshold), e["x"])
    )

    stitched_text = ""
    current_y_group = None
    current_line = []

    for elem in sorted_elements:
        # Determine the group for the current y-coordinate
        y_group = (
            round(elem["y"] / y_grouping_threshold)
            if elem["y"] != float("inf")
            else float("inf")
        )

        # If it's a new line (different y group)
        if current_y_group is None or y_group != current_y_group:
            if current_line:
                # Join words in the completed line
                line_text = " ".join(current_line)
                # Simple punctuation cleanup for the line
                line_text = re.sub(r"\s+([,.!?;:])", r"\1", line_text).strip()
                stitched_text += line_text + "\n"
                current_line = []
            current_y_group = y_group

        # Add text to the current line
        current_line.append(elem["text"])

    # Add the last line
    if current_line:
        line_text = " ".join(current_line)
        line_text = re.sub(r"\s+([,.!?;:])", r"\1", line_text).strip()
        stitched_text += line_text

    return stitched_text.strip()


def extract_text_and_coordinates(
    parsed_data, image_dimensions=None, coordinate_format="percent"
):
    """
    Extracts text and coordinates from the parsed data structure.
    Coordinates in bbox are typically relative (0-1). Pixel conversion requires original dimensions.
    Angle is added in degrees.
    """
    text_with_coords = []
    word_annotations = parsed_data.get("word_annotations", [])

    if coordinate_format == "pixels" and not image_dimensions:
        logging.warning(
            "Image dimensions needed for pixel conversion, returning relative coordinates."
        )
        coordinate_format = "percent"  # Fallback

    if not isinstance(word_annotations, list):
        logging.error("Word annotations format invalid, expected a list.")
        return []

    for item in word_annotations:
        text = item.get("text")
        bbox_orig = item.get(
            "bbox"
        )  # Original bbox [center_y, center_x, height, width, angle_rad?, conf?]
        angle_deg = item.get("angle_degrees")  # Already converted angle

        if text is None or bbox_orig is None:
            logging.warning(f"Skipping annotation due to missing text or bbox: {item}")
            continue

        if not isinstance(bbox_orig, list) or len(bbox_orig) < 4:
            logging.warning(
                f"Skipping annotation due to invalid bbox format: {bbox_orig}"
            )
            continue

        # --- Coordinate Conversion ---
        coords_to_store = list(bbox_orig)  # Make a copy

        if coordinate_format == "pixels":
            try:
                img_width, img_height = image_dimensions
                # Assuming bbox format: [center_y, center_x, height, width, ...]
                center_y_rel, center_x_rel, height_rel, width_rel = bbox_orig[:4]

                center_y_px = center_y_rel * img_height
                center_x_px = center_x_rel * img_width
                height_px = height_rel * img_height
                width_px = width_rel * img_width

                # Replace the first four elements with pixel values
                coords_to_store[:4] = [center_y_px, center_x_px, height_px, width_px]

            except Exception as e:
                logging.error(
                    f"Error converting coordinates to pixels for bbox {bbox_orig}: {e}. Using relative."
                )
                # Keep coords_to_store as the original relative values if conversion fails

        coord_entry = {
            "text": text,
            "coordinates": coords_to_store,  # This is the potentially converted bbox list
        }
        # Add angle in degrees if available
        if angle_deg is not None:
            coord_entry["angle_degrees"] = angle_deg

        text_with_coords.append(coord_entry)

    return text_with_coords


# This function is less relevant now as full text is reconstructed directly
# def extract_full_text(data):
#     """Retrieves the full text from a data structure (Old Method - Deprecated)."""
#     # ... (keep old implementation commented out or remove) ...
#     return "Full text extraction method needs update for new API response."


def simplify_output(parsed_data, image_dimensions=None, coordinate_format="percent"):
    """Simplified the parsed data structure by extracting key elements."""
    simplified = {}

    if not isinstance(parsed_data, dict):
        logging.error("Invalid parsed_data format received in simplify_output.")
        simplified["error"] = "Invalid input data structure"
        return simplified

    try:
        simplified["language"] = parsed_data.get("language", "und")

        # Reconstructed full text (already joined blocks)
        reconstructed_blocks = parsed_data.get("reconstructed_blocks", [])
        simplified["full_text"] = "\n".join(
            reconstructed_blocks
        )  # This is the primary full text now

        # Extract text with coordinates (including degree conversion and pixel option)
        word_annotations = parsed_data.get("word_annotations", [])
        text_with_coords = extract_text_and_coordinates(
            parsed_data, image_dimensions, coordinate_format
        )
        simplified["text_with_coordinates"] = (
            text_with_coords  # List of dicts {"text": t, "coordinates": bbox, "angle_degrees": d}
        )

        # Stitching methods using the extracted word annotations
        # Note: These might produce different results than the old methods due to structure changes
        simplified["stitched_text_smart"] = stitch_text_smart(word_annotations)
        simplified["stitched_text_sequential"] = stitch_text_sequential(
            word_annotations
        )

    except Exception as e:
        logging.error(
            f"Error in simplify_output processing parsed data: {e}", exc_info=True
        )
        simplified["error"] = f"Error during output simplification: {e}"

    return simplified
