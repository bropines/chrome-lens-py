# constants.py

LENS_ENDPOINT = 'https://lens.google.com/v3/upload'

SUPPORTED_MIMES = [
    'image/x-icon',
    'image/bmp',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'image/webp',
    'image/heic'
]

MIME_TO_EXT = {
    'image/x-icon': 'ico',
    'image/bmp': 'bmp',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/tiff': 'tiff',
    'image/webp': 'webp',
    'image/heic': 'heic'
}

HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'max-age=0',
    'Origin': 'https://lens.google.com',
    'Referer': 'https://lens.google.com/',
    'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
    'Sec-Ch-Ua-Arch': '"x86"',
    'Sec-Ch-Ua-Bitness': '"64"',
    'Sec-Ch-Ua-Full-Version': '"91.0.4472.124"',
    'Sec-Ch-Ua-Full-Version-List': '"Not A(Brand";v="99.0.0.0", "Google Chrome";v="91", "Chromium";v="91"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Model': '""',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Ch-Ua-Platform-Version': '"15.0.0"',
    'Sec-Ch-Ua-Wow64': '?0',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'X-Client-Data': 'CIW2yQEIorbJAQipncoBCIH+ygEIlaHLAQj1mM0BCIWgzQEI3ezNAQji+s0BCOmFzgEIponOAQj1ic4BCIeLzgEY1d3NARjS/s0BGNiGzgE='
}
