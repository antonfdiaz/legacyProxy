(function () {
    var progressBars = document.querySelectorAll(".Progress");
    var container = document.querySelector(
        'include-fragment[aria-label="Loading contributors"]'
    );
    var sibling;
    var i;
    var path;
    var request;

    for (i = 0; i < progressBars.length; i += 1) {
        sibling = progressBars[i].parentNode.nextSibling;
        while (sibling && sibling.nodeType !== 1) {
            sibling = sibling.nextSibling;
        }
        if (sibling && sibling.tagName === "UL") {
            progressBars[i].className += " legacy-language-progress";
            sibling.className += " legacy-languages";
        }
    }

    if (!container) {
        return;
    }

    path = window.location.pathname.split("/");
    if (path.length < 3 || !path[1] || !path[2]) {
        return;
    }

    container.innerHTML =
        '<h2><a href="/' + path[1] + '/' + path[2] +
        '/graphs/contributors">Contributors</a></h2>' +
        '<p class="legacy-contributors-status">Loading contributors...</p>';

    request = new XMLHttpRequest();
    request.open(
        "GET",
        "https://api.github.com/repos/" +
            encodeURIComponent(path[1]) + "/" +
            encodeURIComponent(path[2]) +
            "/contributors?per_page=8&anon=1",
        true
    );
    request.onreadystatechange = function () {
        var contributors;
        var html;
        var contributor;
        var name;

        if (request.readyState !== 4) {
            return;
        }

        if (request.status < 200 || request.status >= 300) {
            container.innerHTML =
                '<h2><a href="/' + path[1] + '/' + path[2] +
                '/graphs/contributors">Contributors</a></h2>' +
                '<p class="legacy-contributors-status">Could not load contributors.</p>';
            return;
        }

        contributors = JSON.parse(request.responseText);
        html =
            '<h2><a href="/' + path[1] + '/' + path[2] +
            '/graphs/contributors">Contributors</a></h2>' +
            '<ul class="legacy-contributors">';

        for (i = 0; i < contributors.length; i += 1) {
            contributor = contributors[i];
            name = contributor.login || contributor.name || "Anonymous";
            html += "<li>";

            if (contributor.html_url) {
                html += '<a href="' + contributor.html_url + '">';
            }
            if (contributor.avatar_url) {
                html += '<img src="' + contributor.avatar_url +
                    '&s=64" alt="">';
            }
            html += '<span class="legacy-contributor-name">' + escapeHtml(name) + "</span>";
            if (contributor.html_url) {
                html += "</a>";
            }
            html += "<small>" + contributor.contributions + " contributions</small></li>";
        }

        container.innerHTML = html + "</ul>";
    };
    request.send(null);

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g,"&amp;")
            .replace(/</g,"&lt;")
            .replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;");
    }
}());
