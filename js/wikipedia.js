(function () {
    var images = document.getElementsByTagName("img");
    var retryNumber = 0;
    var i;

    function retryImage(image) {
        var source;
        var separator;
        var delay;
        var attempt;

        if (!image) {
            return;
        }

        attempt = parseInt(image.getAttribute("data-legacy-retry-count") || "0",10);
        if (attempt >= 2) {
            return;
        }

        source = image.getAttribute("data-legacy-original-src") || image.getAttribute("src");
        if (!source || source.indexOf("data:") === 0) {
            return;
        }

        attempt += 1;
        image.setAttribute("data-legacy-retry-count",attempt);
        image.setAttribute("data-legacy-original-src",source);
        separator = source.indexOf("?") === -1 ? "?" : "&";
        delay = 100 + retryNumber * 75;
        retryNumber += 1;

        window.setTimeout(function () {
            image.src = source + separator + "legacy-retry=" + attempt;
        }, delay);
    }

    for (i = 0; i < images.length; i++) {
        images[i].onerror = function () {
            retryImage(this);
        };

        if (images[i].complete && images[i].naturalWidth === 0) {
            retryImage(images[i]);
        }
    }
}());
