# legacyProxy
legacyProxy is a MITM proxy that fixes some websites on legacy iOS devices.
Currently it fixes Reddit, Google Search and Wikipedia image loading.
Tested on iOS 6 and iOS 8. Fixes every browser that uses WebKit (Chrome, Opera Mini, Safari, etc).

## Reddit
Redirects `reddit.com` URLs to `old.reddit.com` and modifies its CSS to work better on old Safari/WebKit.
Reddit works better on iOS 8 than on iOS 6 from what I've tested.

## Google Search
Scrapes Google Search results and builds the results page from a local *HTML template*.
The CSS applied is like the modern Google search (a bit older but still modern).
Google works correctly on every version I've tested.

## Wikipedia
Rewrites Wikimedia image URLs through the proxy and removes the unsupported `srcset`, `loading`, and `decoding` attributes from Wikipedia pages so images load correctly on legacy iOS Safari.
Wikipedia works correctly on every version I've tested.

## TODO
To-do for website fixing. I will NOT be fixing websites that already work with an app, such as eBay, YouTube, Instagram, etc.
- [x] Google Search
- [x] Reddit
- [x] Wikipedia
- [ ] GitHub
- [ ] Amazon
