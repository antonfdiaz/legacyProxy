(function () {
    var menu = document.getElementById("main-menu-input");
    var mask = document.querySelector(".main-menu-mask");

    if (!menu || !mask) {
        return;
    }

    function closeMenu(event) {
        menu.checked = false;
        menu.setAttribute("aria-expanded","false");
        if (event && event.preventDefault) {
            event.preventDefault();
        }
        return false;
    }

    mask.onclick = closeMenu;
    mask.ontouchend = closeMenu;
}());
