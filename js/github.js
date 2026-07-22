(function () {
    var progressBars = document.querySelectorAll(".Progress")
    var contributors = document.querySelector(
        'include-fragment[aria-label="Loading contributors"]'
    )
    var releaseAssets = document.querySelectorAll(
        'include-fragment[src*="/releases/expanded_assets/"]'
    )
    var issueSearch = document.getElementById("repository-input")
    var issueViewer = document.querySelector('[data-testid="issue-viewer-container"]')
    var pullSearch = document.getElementById("js-issues-search")
    var pullTimeline = document.querySelector(".pull-discussion-timeline")
    var userProfile = document.querySelector(".js-profile-editable-area")
    var profileContributions = document.querySelector(
        'include-fragment[src*="tab=contributions"]'
    )
    var sibling
    var i

    function loadFragment(container,className,accept,requestedWith,onload) {
        var request
        var source = container.getAttribute("src")

        if (!source) {
            return
        }

        request = new XMLHttpRequest()
        request.open("GET",source,true)
        request.setRequestHeader("Accept",accept || "text/fragment+html")
        if (requestedWith) {
            request.setRequestHeader("X-Requested-With","XMLHttpRequest")
        }
        request.onreadystatechange = function () {
            if (request.readyState !== 4) {
                return
            }

            if (request.status < 200 || request.status >= 300) {
                if (requestedWith) {
                    container.className += " legacy-fragment-error"
                }
                return
            }

            container.innerHTML = request.responseText
            container.className += " " + className
            if (onload) {
                onload(container)
            }
        }
        request.send(null)
    }

    function issueQuery(state) {
        var query = issueSearch.value || "is:issue state:open"

        query = query.replace(/state:(open|closed)/,"state:" + state)
        if (query.indexOf("state:") === -1) {
            query += " state:" + state
        }
        return window.location.pathname + "?q=" + encodeURIComponent(query)
    }

    function submitIssueSearch() {
        window.location.href = window.location.pathname + "?q=" +
            encodeURIComponent(issueSearch.value)
    }

    function bindProfileActivity(container) {
        var summaries = container.querySelectorAll(
            ".contribution-activity-listing summary"
        )
        var j

        for (j = 0; j < summaries.length; j += 1) {
            var control = summaries[j].querySelector(".Details-content--open")
            var details = summaries[j].parentNode
            var toggle

            if (!control) {
                continue
            }

            control = control.parentNode
            toggle = document.createElement("button")
            toggle.type = "button"
            toggle.className = "legacy-details-toggle"
            toggle.setAttribute("aria-label","Collapse contribution details")
            while (control.firstChild) {
                toggle.appendChild(control.firstChild)
            }
            summaries[j].removeChild(control)
            details.parentNode.insertBefore(toggle,details.nextSibling)

            toggle.onclick = function (clickEvent) {
                var event = clickEvent || window.event
                var currentDetails = this.previousSibling
                var summary = currentDetails.getElementsByTagName("summary")[0]

                if (event.preventDefault) {
                    event.preventDefault()
                }
                if (event.stopPropagation) {
                    event.stopPropagation()
                }
                event.returnValue = false
                event.cancelBubble = true

                if (currentDetails.hasAttribute("open")) {
                    currentDetails.removeAttribute("open")
                    summary.setAttribute("aria-expanded","false")
                    this.setAttribute("aria-label","Expand contribution details")
                } else {
                    currentDetails.setAttribute("open","")
                    summary.setAttribute("aria-expanded","true")
                    this.setAttribute("aria-label","Collapse contribution details")
                }
                return false
            }
        }
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

    if (issueSearch) {
        document.body.className += " legacy-issues-page"

        var issueSection = document.querySelector('section[aria-label="All issues"]')
        var issueSearchButton = document.querySelector(
            '#repository button[data-component="IconButton"]'
        )
        var issueStateLinks = issueSection ? issueSection.querySelectorAll(
            'a[data-component="Text"]'
        ) : []

        issueSearch.onkeydown = function (event) {
            event = event || window.event
            if (event.keyCode === 13) {
                submitIssueSearch()
                return false
            }
        }

        if (issueSearchButton) {
            issueSearchButton.onclick = submitIssueSearch
        }

        for (i = 0; i < issueStateLinks.length; i += 1) {
            if (issueStateLinks[i].textContent.indexOf("Open") !== -1) {
                issueStateLinks[i].href = issueQuery("open")
            } else if (issueStateLinks[i].textContent.indexOf("Closed") !== -1) {
                issueStateLinks[i].href = issueQuery("closed")
            }
        }
    }

    if (issueViewer) {
        document.body.className += " legacy-issue-detail"
    }

    if (pullSearch && pullSearch.form &&
        /\/pulls(?:\?|$)/.test(pullSearch.form.action)) {
        document.body.className += " legacy-pulls-page"
    }

    if (pullTimeline) {
        document.body.className += " legacy-pr-detail"
    }

    if (userProfile) {
        document.body.className += " legacy-user-profile"
        bindProfileActivity(document)
    }

    if (profileContributions) {
        profileContributions.className += " legacy-profile-contributions"
        loadFragment(
            profileContributions,
            "legacy-profile-contributions-loaded",
            "text/html",
            true,
            bindProfileActivity
        )
    }
}())
