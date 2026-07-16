(function () {
    var progressBars = document.querySelectorAll(".Progress")
    var container = document.querySelector(
        'include-fragment[aria-label="Loading contributors"]'
    );
    var sibling
    var i
    var request
    var source

    for (i = 0; i < progressBars.length; i += 1) {
        sibling = progressBars[i].parentNode.nextSibling;
        while (sibling && sibling.nodeType !== 1) {
            sibling = sibling.nextSibling
        }
        if (sibling && sibling.tagName === "UL") {
            progressBars[i].className += " legacy-language-progress"
            sibling.className += " legacy-languages"
        }
    }

    if (!container) {
        return
    }

    source = container.getAttribute("src")
    if (!source) {
        return
    }

    request = new XMLHttpRequest()
    request.open("GET",source,true)
    request.onreadystatechange = function () {
        if (request.readyState !== 4) {
            return
        }

        if (request.status < 200 || request.status >= 300) {
            return
        }

        container.innerHTML = request.responseText
        container.className += " legacy-contributors-fragment"
    }
    request.send(null)
}())