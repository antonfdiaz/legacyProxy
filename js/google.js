(function () {
    var menuIcon = document.getElementsByClassName("menu-icon")[0]
    var optionsMenu = document.getElementById("options-menu")
    var closeMenuButton = document.getElementById("close-menu")

    function openMenu() {
        optionsMenu.style.left = "0px"
        menuIcon.setAttribute("aria-expanded","true")
    }

    function closeMenu() {
        optionsMenu.style.left = "-200px"
        menuIcon.setAttribute("aria-expanded","false")
    }

    menuIcon.onclick = function (event) {
        event = event || window.event
        if (event.stopPropagation) {
            event.stopPropagation()
        } else {
            event.cancelBubble = true
        }

        if (optionsMenu.style.left === "0px") {
            closeMenu()
        } else {
            openMenu()
        }
    }

    optionsMenu.onclick = function (event) {
        event = event || window.event
        if (event.stopPropagation) {
            event.stopPropagation()
        } else {
            event.cancelBubble = true
        }
    }

    closeMenuButton.onclick = closeMenu
    document.onclick = closeMenu
}())