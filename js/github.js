(function () {
    var progressBars = document.querySelectorAll(".Progress")
    var contributors = document.querySelector(
        'include-fragment[aria-label="Loading contributors"]'
    )
    var releaseAssets = document.querySelectorAll(
        'include-fragment[src*="/releases/expanded_assets/"]'
    )
    var sibling
    var i

    function loadFragment(container,className) {
        var request
        var source = container.getAttribute("src")

        if (!source) {
            return
        }

        request = new XMLHttpRequest()
        request.open("GET",source,true)
        request.setRequestHeader("Accept","text/fragment+html")
        request.onreadystatechange = function () {
            if (request.readyState !== 4) {
                return
            }

            if (request.status < 200 || request.status >= 300) {
                return
            }

            container.innerHTML = request.responseText
            container.className += " " + className
        }
        request.send(null)
    }

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

    if (contributors) {
        loadFragment(contributors,"legacy-contributors-fragment")
    }

    for (i = 0; i < releaseAssets.length; i += 1) {
        loadFragment(releaseAssets[i],"legacy-release-assets")
    }
}())
