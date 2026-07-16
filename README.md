# <img height="120" alt="legacyproxy-banner" src="https://github.com/user-attachments/assets/e1cf10e7-55da-4c6b-aa39-49d88f2606b1" />
legacyProxy is a MITM proxy that fixes some websites on legacy iOS devices.
Currently it fixes Reddit, Google Search, Wikipedia image loading and GitHub repository pages.
Tested on iOS 3, iOS 6 and iOS 8. Fixes every browser that uses WebKit (Chrome, Opera Mini, Safari, etc).

### Reddit
Redirects `reddit.com` URLs to `old.reddit.com` and modifies its CSS to work better on old Safari/WebKit.  
Reddit looks a bit better on iOS 8+ than on iOS 3 and 6.

### Google Search
Scrapes Google Search results and builds the results page from a local *HTML template*.
The CSS applied is like the modern Google search.
Google looks better on iOS 6+.

### Wikipedia
Rewrites Wikimedia image URLs through the proxy and removes the unsupported `srcset`, `loading`, and `decoding` attributes from Wikipedia pages so images load correctly on legacy iOS Safari.
Wikipedia works correctly on every version I've tested.

### GitHub
Injects a compatible stylesheet into GitHub pages. Repo headers, navigation, file listings, README files and sidebars use a simple single-column layout that doesn't depend on modern CSS grid or flexbox support.  
GitHub works better on iOS 6+.

## Usage
### How to run
- Make a venv inside the proxy folder: `python3 -m venv .venv`
- Activate it: `source .venv/bin/activate` (`.venv/Scripts/activate` on Windows)
- Install libraries: `pip install -r requirements.txt`
- Start the proxy: `python main.py`

### Configure Device
Go to Settings -> Wi-Fi -> The button next to the selected network -> Go to the bottom -> HTTP Proxy:
- Set it to `Manual`
- Server: Your PC's IP address
- Port: `8080`
- Authentication: OFF

That's it! You can now use Google, Reddit and more on your old iPhone!

## TODO
To-do for website fixing. I will NOT be fixing websites that already work with an app, such as eBay, YouTube, Instagram, etc.
- [x] Google Search
  - [x] Web search
  - [x] Image search
  - [ ] Video search
- [x] Reddit
  - [x] Browse Reddit
  - [ ] Login
- [x] Wikipedia
  - [x] Image loading
  - [ ] Fix CSS
- [x] GitHub
  - [x] Repo page
  - [x] Releases/Tags
  - [x] Issue pages
  - [ ] PRs page
  - [ ] User page
  - [ ] Login
- [ ] Amazon
