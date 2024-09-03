import sys
import argparse
from .lens_api import LensAPI
from rich.console import Console

console = Console()

def print_help():
    console.print("Usage: [b]lens_scan [options] <image_file> <data_type>[/b]")
    console.print("\nOptions:")
    console.print("[b]-h, --help[/b]                Show this help message and exit")
    console.print("[b]-c, --cookie-file[/b]         Path to the Netscape cookie file")
    console.print("[b]-p, --proxy[/b]               Specify proxy server (e.g., socks5://user:pass@host:port)")
    console.print("\n[b]<data_type>[/b] options:")
    console.print("[b]all[/b]                       Get all data (full text, coordinates, and stitched text)")
    console.print("[b]full_text_defaul  t[/b]         Get only the default full text")
    console.print("[b]full_text_old_method[/b]      Get stitched text using the old method")
    console.print("[b]full_text_new_method[/b]      Get stitched text using the new method")
    console.print("[b]coordinates[/b]               Get text with coordinates")
    console.print("[b]-c, --cookie-file[/b]         Path to the Netscape cookie file")

def main():
    parser = argparse.ArgumentParser(description="Process images with Google Lens API and extract text data.", add_help=False)
    parser.add_argument('image_file', nargs='?', help="Path to the image file")
    parser.add_argument('data_type', nargs='?', choices=['all', 'full_text_default', 'full_text_old_method', 'full_text_new_method', 'coordinates'], help="Type of data to extract")
    parser.add_argument('-h', '--help', action='store_true', help="Show this help message and exit")
    parser.add_argument('-c', '--cookie-file', help="Path to the Netscape cookie file")
    parser.add_argument('-p', '--proxy', help="Proxy server (e.g., socks5://user:pass@host:port)")
    
    args = parser.parse_args()

    if args.help or not args.image_file or not args.data_type:
        print_help()
        sys.exit(1)

    config = {}
    if args.cookie_file:
        config['headers'] = {'cookie': args.cookie_file}
    if args.proxy:
        config['proxy'] = args.proxy

    api = LensAPI(config=config)

    image_file = args.image_file
    data_type = args.data_type

    try:
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
            console.print("[red]Invalid data type specified.[/red]")
            sys.exit(1)

        # Output result
        console.print(result)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
