import sys
import json
import argparse
from .lens_api import LensAPI
from rich.console import Console
from rich.table import Table

console = Console()

def print_help():
    console.print("Usage: [b]lens_scan [options] <image_file> <data_type>[/b]")
    console.print("\nOptions:")
    console.print("[b]-h, --help[/b]          Show this help message and exit")
    console.print("[b]<data_type>[/b] options:")
    console.print("[b]all[/b]                      Get all data (full text, coordinates, and stitched text)")
    console.print("[b]full_text_default[/b]        Get only the default full text")
    console.print("[b]full_text_old_method[/b]     Get stitched text using the old method")
    console.print("[b]full_text_new_method[/b]     Get stitched text using the new method")
    console.print("[b]coordinates[/b]              Get text with coordinates")

def main():
    parser = argparse.ArgumentParser(description="Process images with Google Lens API and extract text data.", add_help=False)
    parser.add_argument('image_file', nargs='?', help="Path to the image file")
    parser.add_argument('data_type', nargs='?', choices=['all', 'full_text_default', 'full_text_old_method', 'full_text_new_method', 'coordinates'], help="Type of data to extract")
    parser.add_argument('-h', '--help', action='store_true', help="Show this help message and exit")

    args = parser.parse_args()

    if args.help or not args.image_file or not args.data_type:
        print_help()
        sys.exit(1)

    image_file = args.image_file
    data_type = args.data_type

    try:
        api = LensAPI()

        if data_type == "all":
            result = api.get_all_data(image_file)
        elif data_type == "full_text_default":
            result = api.get_full_text(image_file)
        elif data_type == "full_text_old_method":
            result = api.get_stitched_text_sequential(image_file)
        elif data_type == "full_text_new_method":
            result = api.get_stitched_text_smart(image_file)
        elif data_type == "coordinates":
            result = api.get_text_with_coordinates(image_file)
        else:
            console.print("Invalid data_type option", style="bold red")
            sys.exit(1)

        console.print(json.dumps(result, indent=2), style="bold white")

    except Exception as e:
        console.print(f"Error: {e}", style="bold red")

if __name__ == '__main__':
    main()
