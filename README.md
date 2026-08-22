# <img height="120" alt="legacyproxy-banner" src="https://github.com/user-attachments/assets/e1cf10e7-55da-4c6b-aa39-49d88f2606b1" />
legacyProxy is a MITM proxy that fixes some websites on legacy iOS devices.

Currently it fixes Reddit, Google Search, Wikipedia image loading and GitHub.
Tested on iOS 3 (iPhone 3G), iOS 6 (iPhone 4S) and iOS 8 (iPod touch 5). It works with every browser that uses WebKit on iOS (Chrome, Opera Mini, Safari, etc).

<img height="250" alt="IMG_0040" src="https://github.com/user-attachments/assets/0d1ca776-de72-4435-ac21-155876e0d7ac" />
<img height="250" alt="IMG_0038" src="https://github.com/user-attachments/assets/cd1d3bde-5b5b-4bee-9d2e-505c51ef8ce1" />
<img height="250" alt="IMG_0037" src="https://github.com/user-attachments/assets/e890473c-9b1c-4ca9-86d1-ea236d2992de" />
<img height="250" alt="IMG_0035" src="https://github.com/user-attachments/assets/f3e8866e-9720-49ff-b224-52bd9391024d" />

## Layout Patches
legacyProxy adapts the CSS and HTML of the websites you visit in real time, so it fixes the layout a bit on old Safari/WebKit. It isn't perfect, but most sites look better thanks to this.

## Website Fixes

### Reddit
Uses a custom frontend that looks like old Reddit and gets the data from the Reddit API using the website token. The token is updated every 24 hours automatically so Reddit doesn't stop working in the device.

### Google Search
Scrapes Google Search results and builds the results page from a local *HTML template*.
The CSS applied is like the modern Google search.
Google looks better on iOS 6+.  
**Note**: if Google Search doesn't work, **uncheck** "Chrome Headless" in the proxy settings.

### Wikipedia
Rewrites Wikimedia image URLs through the proxy and removes the unsupported `srcset`, `loading`, and `decoding` attributes from Wikipedia pages so images load correctly on legacy iOS Safari.
Wikipedia works correctly on every version I've tested.

### GitHub
Injects custom CSS and JS into GitHub pages. Repo headers, navigation, file listings, README files and sidebars use a simple single-column layout that doesn't depend on modern CSS grid or flexbox support.  
GitHub works better on iOS 6+.

## App Fixes

### Reddit
Fixes iReddit, Alien Blue and the modern Reddit app. Uses the Reddit token for the API calls and fixes some other stuff. Login not tested.

<img height="350" alt="IMG_0221" src="https://github.com/user-attachments/assets/3a1864d3-cc32-4d6a-98b1-97e820b4d3fb" />
<img height="350" alt="IMG_0219" src="https://github.com/user-attachments/assets/bc0d3e37-41c8-479b-8c8f-7cb72063b75d" />
<img height="350" alt="IMG_0220" src="https://github.com/user-attachments/assets/00ff439f-74a7-4d5f-b569-32703612030f" />

### IMDb App
Work in progress. Most things work but there are some blank sections and there's an error popup constantly showing up.

## Requirements
- Python 3
- Linux or macOS (Windows support soon)
  
## Usage
### How to run
- Make a venv inside the proxy folder: `python -m venv .venv`
- Activate it: `source .venv/bin/activate` (`.venv/Scripts/activate` on Windows)
- Install libraries: `pip install -r requirements.txt`
- Install Chrome: `patchright install chrome`
- Start the proxy: `python main.py`

### Configure Device
There is no jailbreak needed (but it's recommended). You just need to do it like this:  
Go to Settings -> Wi-Fi -> The button next to the selected network -> Go to the bottom -> HTTP Proxy:
- Set it to `Manual`
- Server: Your PC's IP address
- Port: `8080`
- Authentication: OFF

Then open Safari, go to `mitm.it` and install the iOS certificate.

That's it! You can now use Google, Reddit, GitHub and more on your old iDevice!

## TODO
To-do for website fixing. I will not be fixing websites that already work well with an app, such as YouTube, Instagram, etc.
- [x] Google Search
  - [x] Modern homepage
  - [x] Web search
  - [x] Image search
- [x] Reddit
  - [x] Browse Reddit
- [x] Wikipedia
  - [x] Image loading
  - [x] Fix CSS
  - [x] Fix JavaScript
- [x] GitHub
  - [x] Repo page
  - [x] Releases/Tags
  - [x] Issue pages
  - [x] PRs page
  - [x] User page
  - [ ] Home page
- [ ] Stack Overflow
- [ ] IMDb
