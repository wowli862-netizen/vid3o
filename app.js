// ============================================================
// STATE
// ============================================================

let token = localStorage.getItem("isrtube_token");
let currentUser = null;
let currentVideo = null;
let websocket = null;
let authMode = "login";


// ============================================================
// ELEMENTS
// ============================================================

const homePage = document.getElementById("homePage");
const watchPage = document.getElementById("watchPage");
const profilePage = document.getElementById("profilePage");
const aboutPage = document.getElementById("aboutPage");

const videoGrid = document.getElementById("videoGrid");
const profileVideos = document.getElementById("profileVideos");


// ============================================================
// API
// ============================================================

async function api(url, options = {}) {

    options.headers = options.headers || {};

    if (token) {
        options.headers.Authorization =
            `Bearer ${token}`;
    }

    const response =
        await fetch(url, options);

    let data = {};

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {

        throw new Error(
            data.detail ||
            "Произошла ошибка"
        );
    }

    return data;
}


// ============================================================
// INIT
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        setupEvents();
        loadTheme();

        if (token) {

            try {

                const data =
                    await api("/api/me");

                currentUser = data.user;

                updateHeader();

            } catch {

                logout(false);

            }

        }

        connectWebSocket();
        loadVideos();

    }
);


// ============================================================
// EVENTS
// ============================================================

function setupEvents() {

    document
        .getElementById("searchButton")
        .addEventListener(
            "click",
            searchVideos
        );

    document
        .getElementById("searchInput")
        .addEventListener(
            "keydown",
            event => {

                if (event.key === "Enter") {
                    searchVideos();
                }

            }
        );


    document
        .getElementById("themeButton")
        .addEventListener(
            "click",
            toggleTheme
        );


    document
        .getElementById("authForm")
        .addEventListener(
            "submit",
            submitAuth
        );


    document
        .getElementById("switchAuth")
        .addEventListener(
            "click",
            switchAuthMode
        );


    document
        .getElementById("uploadForm")
        .addEventListener(
            "submit",
            uploadVideo
        );


    document
        .getElementById("commentForm")
        .addEventListener(
            "submit",
            submitComment
        );


    document
        .getElementById("likeButton")
        .addEventListener(
            "click",
            likeVideo
        );

}

function openUpload() {

    if (!currentUser) {
        openAuth();
        return;
    }

    const modal =
        document.getElementById(
            "uploadModal"
        );

    if (modal) {

        modal.classList.remove(
            "hidden"
        );

    }

}

// ============================================================
// NAVIGATION
// ============================================================

function hidePages() {

    homePage.classList.add("hidden");
    watchPage.classList.add("hidden");
    profilePage.classList.add("hidden");
    aboutPage.classList.add("hidden");

}


function showHome() {

    hidePages();

    homePage.classList.remove("hidden");

    document
        .getElementById("pageTitle")
        .textContent = "Главная";

    document
        .getElementById("pageSubtitle")
        .textContent =
        "Последние видео на IsrTube";

    loadVideos();

}


function showTrending() {

    hidePages();

    homePage.classList.remove("hidden");

    document
        .getElementById("pageTitle")
        .textContent = "В тренде";

    document
        .getElementById("pageSubtitle")
        .textContent =
        "Популярные видео";

    loadVideos();


}


function showSubscriptions() {

    if (!currentUser) {

        openAuth();

        return;
    }

    hidePages();

    homePage.classList.remove("hidden");

    document
        .getElementById("pageTitle")
        .textContent = "Подписки";

    document
        .getElementById("pageSubtitle")
        .textContent =
        "Здесь появятся видео каналов, на которые вы подписаны";

    videoGrid.innerHTML = `
        <div class="about-card">
            <h2>Раздел подписок</h2>
            <p>
                Система подписок будет добавлена
                в следующей версии IsrTube.
            </p>
        </div>
    `;

}


function showAbout() {

    hidePages();

    aboutPage.classList.remove("hidden");

}


// ============================================================
// LOAD VIDEOS
// ============================================================

async function loadVideos(search = "") {

    videoGrid.innerHTML =
        `<p>Загрузка видео...</p>`;

    try {

        const data =
            await api(
                `/api/videos?search=${encodeURIComponent(search)}`
            );

        renderVideos(
            data.videos,
            videoGrid
        );

    } catch (error) {

        videoGrid.innerHTML =
            `<p>${escapeHtml(error.message)}</p>`;

    }

}


function renderVideos(videos, container) {

    if (!videos.length) {

        container.innerHTML = `
            <div class="about-card">
                <h2>Видео пока нет</h2>
                <p>
                    Станьте первым автором IsrTube!
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML =
        videos.map(video => {

            const avatar =
                video.ownerAvatar
                    ? `<img src="${video.ownerAvatar}">`
                    : "👤";

            return `

                <article
                    class="video-card"
                    onclick="openVideo('${video.id}')"
                >

                    <div class="thumbnail">

                        <video
                            src="${video.videoUrl}"
                            muted
                            preload="metadata"
                        ></video>

                        <div class="thumbnail-placeholder">
                            ▶
                        </div>

                    </div>

                    <div class="video-info">

                        <div class="video-avatar">
                            ${avatar}
                        </div>

                        <div>

                            <div class="video-title">
                                ${escapeHtml(video.title)}
                            </div>

                            <div class="video-author">
                                ${escapeHtml(video.ownerUsername)}
                            </div>

                            <div class="video-stats">
                                ${formatNumber(video.views)}
                                просмотров
                                •
                                ${formatNumber(video.likes)}
                                лайков
                            </div>

                        </div>

                    </div>

                </article>

            `;

        }).join("");


    // Remove placeholder once video has loaded.

    container
        .querySelectorAll(".thumbnail video")
        .forEach(video => {

            video.addEventListener(
                "loadeddata",
                () => {

                    const placeholder =
                        video.parentElement
                            .querySelector(
                                ".thumbnail-placeholder"
                            );

                    if (placeholder) {
                        placeholder.style.display =
                            "none";
                    }

                }
            );

        });

}


// ============================================================
// SEARCH
// ============================================================

function searchVideos() {

    const query =
        document
            .getElementById("searchInput")
            .value
            .trim();

    hidePages();

    homePage.classList.remove("hidden");

    document
        .getElementById("pageTitle")
        .textContent =
        query
            ? `Поиск: ${query}`
            : "Главная";

    loadVideos(query);

}


// ============================================================
// WATCH VIDEO
// ============================================================

async function openVideo(videoId) {

    try {

        const data =
            await api(
                `/api/videos/${videoId}`
            );

        currentVideo = data.video;

        hidePages();

        watchPage.classList.remove(
            "hidden"
        );

        const player =
            document.getElementById(
                "videoPlayer"
            );

        player.src =
            currentVideo.videoUrl;

        document
            .getElementById("watchTitle")
            .textContent =
            currentVideo.title;

        document
            .getElementById("watchMeta")
            .textContent =
            `${currentVideo.ownerUsername} • ` +
            `${formatNumber(currentVideo.views)} просмотров`;

        document
            .getElementById("watchDescription")
            .textContent =
            currentVideo.description ||
            "Описание отсутствует.";

        document
            .getElementById("likeCount")
            .textContent =
            formatNumber(currentVideo.likes);

        document
            .getElementById("viewCount")
            .textContent =
            `${formatNumber(currentVideo.views)} просмотров`;

        await addView(videoId);

        await loadComments(videoId);

        if (currentUser) {
            await updateLikeState(videoId);
        }

    } catch (error) {

        alert(error.message);

    }

}


async function addView(videoId) {

    try {

        const data =
            await api(
                `/api/videos/${videoId}/view`,
                {
                    method: "POST"
                }
            );

        currentVideo.views =
            data.views;

        document
            .getElementById("viewCount")
            .textContent =
            `${formatNumber(data.views)} просмотров`;

    } catch {
        // Ignore view errors.
    }

}


// ============================================================
// LIKES
// ============================================================

async function likeVideo() {

    if (!currentUser) {

        openAuth();

        return;
    }

    if (!currentVideo) {
        return;
    }

    try {

        const data =
            await api(
                `/api/videos/${currentVideo.id}/like`,
                {
                    method: "POST"
                }
            );

        document
            .getElementById("likeCount")
            .textContent =
            formatNumber(data.likes);

        const button =
            document.getElementById(
                "likeButton"
            );

        button.classList.toggle(
            "liked",
            data.liked
        );

    } catch (error) {

        alert(error.message);

    }

}


async function updateLikeState(videoId) {

    try {

        const data =
            await api(
                `/api/videos/${videoId}/liked`
            );

        document
            .getElementById("likeButton")
            .classList.toggle(
                "liked",
                data.liked
            );

    } catch {
        // Not important.
    }

}


// ============================================================
// COMMENTS
// ============================================================

async function loadComments(videoId) {

    const list =
        document.getElementById(
            "commentsList"
        );

    list.innerHTML =
        "<p>Загрузка комментариев...</p>";

    try {

        const data =
            await api(
                `/api/videos/${videoId}/comments`
            );

        renderComments(data.comments);

    } catch (error) {

        list.innerHTML =
            `<p>${escapeHtml(error.message)}</p>`;

    }

}


function renderComments(comments) {

    const list =
        document.getElementById(
            "commentsList"
        );

    if (!comments.length) {

        list.innerHTML =
            "<p>Комментариев пока нет.</p>";

        return;
    }

    list.innerHTML =
        comments.map(renderComment).join("");

}


function renderComment(comment) {

    const avatar =
        comment.avatar
            ? `<img src="${comment.avatar}">`
            : "👤";

    return `

        <div
            class="comment"
            data-comment-id="${comment.id}"
        >

            <div class="comment-avatar">
                ${avatar}
            </div>

            <div>

                <div class="comment-name">
                    ${escapeHtml(comment.username)}
                </div>

                <div class="comment-text">
                    ${escapeHtml(comment.text)}
                </div>

            </div>

        </div>

    `;

}


async function submitComment(event) {

    event.preventDefault();

    if (!currentUser) {
        openAuth();
        return;
    }

    if (!currentVideo) {
        return;
    }

    const input =
        document.getElementById("commentInput");

    if (!input) {
        return;
    }

    const text =
        input.value.trim();

    if (!text) {
        return;
    }

    try {

        const data = await api(
            `/api/videos/${currentVideo.id}/comments`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    user_id: currentUser.id,
                    text: text
                })
            }
        );

        // Очищаем поле
        input.value = "";

        // Сразу показываем новый комментарий
        if (data.comment) {

            const list =
                document.getElementById(
                    "commentsList"
                );

            if (list) {

                // Если это был первый комментарий,
                // убираем сообщение "Комментариев пока нет"
                const emptyMessage =
                    list.querySelector("p");

                if (emptyMessage) {
                    list.innerHTML = "";
                }

                list.insertAdjacentHTML(
                    "afterbegin",
                    renderComment(data.comment)
                );

            }

        } else {

            // Если backend не вернул комментарий,
            // просто обновляем список
            await loadComments(
                currentVideo.id
            );

        }

        // Сообщаем другим подключённым клиентам
        sendWebSocketMessage({
            type: "comment",
            video_id: currentVideo.id
        });

    } catch (error) {

        console.error(
            "Ошибка добавления комментария:",
            error
        );

        alert(
            error.message ||
            "Не удалось добавить комментарий."
        );

    }
}

// ============================================================
// AUTH
// ============================================================

function openAuth() {

    document
        .getElementById("authModal")
        .classList.remove("hidden");

}


function switchAuthMode() {

    authMode =
        authMode === "login"
            ? "register"
            : "login";

    const registerBlock =
        document.getElementById(
            "registerUsername"
        );

    const title =
        document.getElementById(
            "authTitle"
        );

    const submit =
        document.getElementById(
            "authSubmit"
        );

    const switchButton =
        document.getElementById(
            "switchAuth"
        );

    if (authMode === "register") {

        registerBlock.classList.remove(
            "hidden"
        );

        title.textContent =
            "Создать аккаунт";

        submit.textContent =
            "Зарегистрироваться";

        switchButton.textContent =
            "Уже есть аккаунт? Войти";

    } else {

        registerBlock.classList.add(
            "hidden"
        );

        title.textContent =
            "Вход";

        submit.textContent =
            "Войти";

        switchButton.textContent =
            "Нет аккаунта? Зарегистрироваться";

    }

}


async function submitAuth(event) {

    event.preventDefault();

    const email =
        document
            .getElementById("emailInput")
            .value
            .trim();

    const password =
        document
            .getElementById("passwordInput")
            .value;

    const formData =
        new FormData();

    formData.append(
        "email",
        email
    );

    formData.append(
        "password",
        password
    );

    let endpoint;

    if (authMode === "register") {

        const username =
            document
                .getElementById("usernameInput")
                .value
                .trim();

        formData.append(
            "username",
            username
        );

        endpoint =
            "/api/register";

    } else {

        endpoint =
            "/api/login";

    }

    const errorElement =
        document.getElementById(
            "authError"
        );

    errorElement.textContent = "";

    try {

        const data =
            await api(
                endpoint,
                {
                    method: "POST",
                    body: formData
                }
            );

        token =
            data.token;

        currentUser =
            data.user;

        localStorage.setItem(
            "isrtube_token",
            token
        );

        closeModal(
            "authModal"
        );

        updateHeader();

    } catch (error) {

        errorElement.textContent =
            error.message;

    }

}


// ============================================================
// LOGOUT
// ============================================================

function logout(showMessage = true) {

    token = null;
    currentUser = null;

    localStorage.removeItem(
        "isrtube_token"
    );

    updateHeader();

    if (showMessage) {
        alert("Вы вышли из аккаунта.");
    }

}


function updateHeader() {

    const avatar =
        document.getElementById(
            "headerAvatar"
        );

    if (!currentUser) {

        avatar.textContent = "👤";

        document
            .getElementById(
                "userButton"
            )
            .onclick = openAuth;

        return;
    }

    if (currentUser.avatar) {

        avatar.innerHTML =
            `<img src="${currentUser.avatar}">`;

    } else {

        avatar.textContent = "👤";

    }

}


// ============================================================
// PROFILE
// ============================================================

async function openProfile(username = null) {

    if (!username) {

        if (!currentUser) {

            openAuth();

            return;
        }

        username =
            currentUser.username;

    }

    try {

        const data =
            await api(
                `/api/users/${encodeURIComponent(username)}`
            );

        hidePages();

        profilePage.classList.remove(
            "hidden"
        );

        renderProfile(
            data.user,
            data.videos
        );

    } catch (error) {

        alert(error.message);

    }

}


function renderProfile(user, videos) {

    const avatar =
        user.avatar
            ? `<img src="${user.avatar}">`
            : "👤";

    document
        .getElementById("profileHeader")
        .innerHTML = `

            <div class="profile-avatar">
                ${avatar}
            </div>

            <div class="profile-info">

                <h1>
                    ${escapeHtml(user.username)}
                </h1>

                <p>
                    Участник IsrTube
                </p>

                ${
                    currentUser &&
                    currentUser.username === user.username
                        ? `
                            <button
                                class="action-button"
                                onclick="uploadAvatar()"
                            >
                                Изменить аватар
                            </button>
                        `
                        : ""
                }

            </div>
        `;

    renderVideos(
        videos,
        profileVideos
    );

}
// ============================================================
// UPLOAD AVATAR
// ============================================================

async function uploadAvatar() {

    if (!currentUser) {
        openAuth();
        return;
    }

    const input = document.createElement("input");

    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";

    input.onchange = async () => {

        const file = input.files[0];

        if (!file) {
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            alert("Аватар слишком большой. Максимальный размер — 5 МБ.");
            return;
        }

        const formData = new FormData();

        formData.append(
            "avatar",
            file
        );

        try {

            const data = await api(
                "/api/avatar",
                {
                    method: "POST",
                    body: formData
                }
            );

            currentUser.avatar =
                data.avatar;

            updateHeader();

            await openProfile(
                currentUser.username
            );

        } catch (error) {

            console.error(
                "Ошибка загрузки аватара:",
                error
            );

            alert(
                error.message ||
                "Не удалось загрузить аватар."
            );

        }

    };

    input.click();
}

// ============================================================
// VIDEO UPLOAD
// ============================================================

async function uploadVideo(event) {

    event.preventDefault();

    if (!currentUser) {
        openAuth();
        return;
    }

    const titleInput =
        document.getElementById(
            "uploadTitle"
        );

    const descriptionInput =
        document.getElementById(
            "uploadDescription"
        );

    const videoInput =
        document.getElementById(
            "videoFile"
        );

    const errorElement =
        document.getElementById(
            "uploadError"
        );

    const progress =
        document.getElementById(
            "uploadProgress"
        );

    const progressBar =
        document.getElementById(
            "progressBar"
        );

    if (!titleInput || !videoInput) {
        return;
    }

    const title =
        titleInput.value.trim();

    const description =
        descriptionInput
            ? descriptionInput.value.trim()
            : "";

    const file =
        videoInput.files[0];

    if (!title) {
        errorElement.textContent =
            "Введите название видео.";
        return;
    }

    if (!file) {
        errorElement.textContent =
            "Выберите видео.";
        return;
    }

    errorElement.textContent = "";

    const formData =
        new FormData();

    formData.append(
        "title",
        title
    );

    formData.append(
        "description",
        description
    );

    formData.append(
        "video",
        file
    );

    try {

        progress.classList.remove(
            "hidden"
        );

        progressBar.style.width =
            "10%";

        const data =
            await api(
                "/api/videos",
                {
                    method: "POST",
                    body: formData
                }
            );

        progressBar.style.width =
            "100%";

        alert(
            "Видео успешно загружено!"
        );

        document
            .getElementById(
                "uploadForm"
            )
            .reset();

        closeModal(
            "uploadModal"
        );

        progress.classList.add(
            "hidden"
        );

        progressBar.style.width =
            "0%";

        await loadVideos();

        if (data.video) {
            openVideo(
                data.video.id
            );
        }

    } catch (error) {

        console.error(
            "Ошибка загрузки видео:",
            error
        );

        errorElement.textContent =
            error.message ||
            "Не удалось загрузить видео.";

        progress.classList.add(
            "hidden"
        );

        progressBar.style.width =
            "0%";
    }

}

// ============================================================
// MODALS
// ============================================================

function closeModal(modalId) {

    const modal =
        document.getElementById(
            modalId
        );

    if (modal) {

        modal.classList.add(
            "hidden"
        );

    }

}


function openModal(modalId) {

    const modal =
        document.getElementById(
            modalId
        );

    if (modal) {

        modal.classList.remove(
            "hidden"
        );

    }

}


// ============================================================
// THEME
// ============================================================

function loadTheme() {

    const theme =
        localStorage.getItem(
            "isrtube_theme"
        );

    if (theme === "dark") {

        document.body.classList.add(
            "dark"
        );

    } else {

        document.body.classList.remove(
            "dark"
        );

    }

}


function toggleTheme() {

    document.body.classList.toggle(
        "dark"
    );

    const dark =
        document.body.classList.contains(
            "dark"
        );

    localStorage.setItem(
        "isrtube_theme",
        dark ? "dark" : "light"
    );

}


// ============================================================
// WEBSOCKET
// ============================================================

function connectWebSocket() {

    try {

        const protocol =
            location.protocol === "https:"
                ? "wss:"
                : "ws:";

        websocket =
            new WebSocket(
                `${protocol}//${location.host}/ws`
            );

        websocket.addEventListener(
            "open",
            () => {

                console.log(
                    "WebSocket подключён"
                );

            }
        );

        websocket.addEventListener(
            "message",
            event => {

                try {

                    const data =
                        JSON.parse(
                            event.data
                        );

                    handleWebSocketMessage(
                        data
                    );

                } catch {

                    console.warn(
                        "Получено некорректное WebSocket-сообщение"
                    );

                }

            }
        );

        websocket.addEventListener(
            "close",
            () => {

                console.log(
                    "WebSocket отключён"
                );

                // Пытаемся переподключиться
                setTimeout(
                    connectWebSocket,
                    3000
                );

            }
        );

        websocket.addEventListener(
            "error",
            error => {

                console.error(
                    "WebSocket error:",
                    error
                );

            }
        );

    } catch (error) {

        console.error(
            "Не удалось подключить WebSocket:",
            error
        );

    }

}


function sendWebSocketMessage(data) {

    if (
        websocket &&
        websocket.readyState === WebSocket.OPEN
    ) {

        websocket.send(
            JSON.stringify(data)
        );

    }

}


function handleWebSocketMessage(data) {

    console.log(
        "WebSocket message:",
        data
    );

    /*
     * Здесь позже можно добавить
     * real-time уведомления:
     *
     * - новые комментарии
     * - лайки
     * - новые видео
     * - уведомления
     */

    if (
        data.type === "comment" &&
        currentVideo &&
        data.video_id === currentVideo.id
    ) {

        loadComments(
            currentVideo.id
        );

    }

}


// ============================================================
// HELPERS
// ============================================================

function formatNumber(number) {

    number =
        Number(number) || 0;

    return new Intl.NumberFormat(
        "ru-RU"
    ).format(number);

}


function escapeHtml(value) {

    if (
        value === null ||
        value === undefined
    ) {

        return "";

    }

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

}


// ============================================================
// BACK BUTTON / NAVIGATION HELPERS
// ============================================================

function goBack() {

    if (
        watchPage &&
        !watchPage.classList.contains("hidden")
    ) {

        showHome();

        return;
    }

    if (
        profilePage &&
        !profilePage.classList.contains("hidden")
    ) {

        showHome();

        return;
    }

    showHome();

}


// ============================================================
// CLOSE MODALS WHEN CLICKING OUTSIDE
// ============================================================

document.addEventListener(
    "click",
    event => {

        if (
            event.target.classList.contains(
                "modal"
            )
        ) {

            event.target.classList.add(
                "hidden"
            );

        }

    }
);


// ============================================================
// ESC KEY
// ============================================================

document.addEventListener(
    "keydown",
    event => {

        if (event.key !== "Escape") {
            return;
        }

        document
            .querySelectorAll(".modal")
            .forEach(modal => {

                modal.classList.add(
                    "hidden"
                );

            });

    }
);


// ============================================================
// GLOBAL ERROR HANDLER
// ============================================================

window.addEventListener(
    "error",
    event => {

        console.error(
            "IsrTube error:",
            event.error || event.message
        );

    }
);


// ============================================================
// UNHANDLED PROMISE ERRORS
// ============================================================

window.addEventListener(
    "unhandledrejection",
    event => {

        console.error(
            "Unhandled promise rejection:",
            event.reason
        );

    }
);


// ============================================================
// END OF APP.JS
// ============================================================
