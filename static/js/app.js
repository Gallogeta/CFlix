document.addEventListener("DOMContentLoaded", () => {
    // Base URL path resolver for subpaths (e.g. /media-ops/ or /jellyfin-ops/)
    const BASE_PATH = (function() {
        let p = window.location.pathname;
        if (!p.endsWith('/')) {
            p = p + '/';
        }
        return p;
    })();

    function apiUrl(path) {
        if (!path) return BASE_PATH;
        const clean = path.startsWith('/') ? path.slice(1) : path;
        return BASE_PATH + clean;
    }

    async function apiFetch(endpoint, options = {}) {
        const url = endpoint.startsWith("http") ? endpoint : apiUrl(endpoint);
        const resp = await fetch(url, options);
        if (resp.status === 401) {
            showLoginModal("Session expired or admin credentials required.");
        }
        return resp;
    }

    // Auth Elements & State
    let isAuthenticated = false;
    const loginModalOverlay = document.getElementById("login-modal-overlay");
    const loginForm = document.getElementById("login-form");
    const loginUsernameInput = document.getElementById("login-username");
    const loginPasswordInput = document.getElementById("login-password");
    const loginErrorMsg = document.getElementById("login-error-msg");
    const btnLoginSubmit = document.getElementById("btn-login-submit");
    const userAuthPill = document.getElementById("user-auth-pill");
    const userDisplayName = document.getElementById("user-display-name");
    const btnLogout = document.getElementById("btn-logout");

    function showLoginModal(errorText = "") {
        if (userAuthPill) userAuthPill.style.display = "none";
        if (loginModalOverlay) loginModalOverlay.style.display = "flex";
        if (loginErrorMsg) {
            if (errorText) {
                loginErrorMsg.textContent = errorText;
                loginErrorMsg.style.display = "block";
            } else {
                loginErrorMsg.style.display = "none";
            }
        }
        if (loginUsernameInput) loginUsernameInput.focus();
    }

    function hideLoginModal(username = "Admin") {
        if (loginModalOverlay) loginModalOverlay.style.display = "none";
        if (userAuthPill) userAuthPill.style.display = "flex";
        if (userDisplayName) userDisplayName.textContent = username;
    }

    async function checkAuth() {
        try {
            const resp = await fetch(apiUrl("/api/auth/me"));
            const data = await resp.json();
            if (data.authenticated && (data.is_admin || data.can_manage)) {
                isAuthenticated = true;
                const roleLabel = data.is_admin ? "Admin" : "Manager";
                hideLoginModal(`${data.username || "User"} (${roleLabel})`);
                if (!data.is_admin) {
                    const settingsTabBtn = document.querySelector('[data-tab="settings-tab"]');
                    if (settingsTabBtn) settingsTabBtn.style.display = "none";
                }
                return true;
            } else {
                isAuthenticated = false;
                showLoginModal();
                if (data.server_url) {
                    const serverUrlEl = document.getElementById("login-server-url");
                    if (serverUrlEl && !serverUrlEl.value) serverUrlEl.value = data.server_url;
                }
                return false;
            }
        } catch (e) {
            console.error("Auth check failed:", e);
            showLoginModal("Could not connect to authentication service.");
            return false;
        }
    }

    if (loginForm) {
        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const serverUrlEl = document.getElementById("login-server-url");
            const serverUrl = serverUrlEl ? serverUrlEl.value.trim() : "";
            const username = loginUsernameInput ? loginUsernameInput.value.trim() : "";
            const password = loginPasswordInput ? loginPasswordInput.value.trim() : "";
            if (!username || !password) return;

            if (loginErrorMsg) loginErrorMsg.style.display = "none";
            if (btnLoginSubmit) {
                btnLoginSubmit.disabled = true;
                btnLoginSubmit.innerHTML = "<span>Connecting & Authenticating...</span>";
            }

            try {
                const resp = await fetch(apiUrl("/api/auth/login"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password, server_url: serverUrl })
                });
                let data;
                try {
                    data = await resp.json();
                } catch (jsonErr) {
                    data = { success: false, error: `Authentication failed (Status ${resp.status}). Check server URL and credentials.` };
                }
                if (data.success && (data.is_admin || data.can_manage)) {
                    isAuthenticated = true;
                    const roleLabel = data.is_admin ? "Admin" : "Manager";
                    hideLoginModal(`${data.username || username} (${roleLabel})`);
                    if (!data.is_admin) {
                        const settingsTabBtn = document.querySelector('[data-tab="settings-tab"]');
                        if (settingsTabBtn) settingsTabBtn.style.display = "none";
                    }
                    checkServerStatus();
                    loadSettings();
                    loadMediaDirectories();
                    loadIncomingQueue();
                    connectSseLogs();
                } else {
                    if (loginErrorMsg) {
                        loginErrorMsg.textContent = data.error || "Authentication failed: Valid media server credentials with upload/management permissions required.";
                        loginErrorMsg.style.display = "block";
                    }
                }
            } catch (err) {
                if (loginErrorMsg) {
                    loginErrorMsg.textContent = `Login failed: ${err.message}`;
                    loginErrorMsg.style.display = "block";
                }
            } finally {
                if (btnLoginSubmit) {
                    btnLoginSubmit.disabled = false;
                    btnLoginSubmit.innerHTML = "<span>Connect & Sign In</span>";
                }
            }
        });
    }

    if (btnLogout) {
        btnLogout.addEventListener("click", async () => {
            try {
                await fetch(apiUrl("/api/auth/logout"), { method: "POST" });
            } catch (e) {}
            window.location.reload();
        });
    }

    // State
    let currentUploadedPath = null;
    let selectedMetadata = null;
    let collectionsData = [];
    let isSeries = false;

    // Elements
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const browseBtn = document.getElementById("browse-btn");
    const uploadProgressBox = document.getElementById("upload-progress-box");
    const uploadFileName = document.getElementById("upload-file-name");
    const uploadPercent = document.getElementById("upload-percent");
    const uploadProgressBar = document.getElementById("upload-progress-bar");
    const uploadSpeed = document.getElementById("upload-speed");
    const uploadEta = document.getElementById("upload-eta");
    
    const metaQuery = document.getElementById("meta-query");
    const btnImdbSearch = document.getElementById("btn-imdb-search");
    const imdbSuggestionsList = document.getElementById("imdb-suggestions-list");
    const matchPoster = document.getElementById("match-poster");
    const displayTitle = document.getElementById("display-title");
    const displayYear = document.getElementById("display-year");
    const displayActors = document.getElementById("display-actors");
    const displayImdbId = document.getElementById("display-imdb-id");
    const seriesInputs = document.getElementById("series-inputs");
    const seriesSeason = document.getElementById("series-season");
    const seriesEpisode = document.getElementById("series-episode");
    const seriesEpTitle = document.getElementById("series-ep-title");
    const overwriteToggle = document.getElementById("overwrite-toggle");
    const btnProcessIngest = document.getElementById("btn-process-ingest");

    const queueTableBody = document.getElementById("queue-table-body");
    const queueBadge = document.getElementById("queue-badge");
    const btnRefreshQueue = document.getElementById("btn-refresh-queue");
    const btnBatchSeriesQueue = document.getElementById("btn-batch-series-queue");
    const queueSelectAll = document.getElementById("queue-select-all");

    // Mass Series Ingest Elements & State
    let batchQueue = [];
    let batchSelectedMetadata = null;
    let cachedSeriesEpisodes = [];
    let isBatchProcessing = false;
    let incomingQueueFiles = [];

    const btnModeSingle = document.getElementById("btn-mode-single");
    const btnModeSeries = document.getElementById("btn-mode-series");
    const singleUploadView = document.getElementById("single-upload-view");
    const seriesBatchView = document.getElementById("series-batch-view");
    const seriesBatchBadge = document.getElementById("series-batch-badge");

    const folderInput = document.getElementById("folder-input");
    const browseFolderBtn = document.getElementById("browse-folder-btn");
    const batchDropZone = document.getElementById("batch-drop-zone");

    // Metadata Search Source State
    let currentSingleSource = 'imdb';
    let currentBatchSource = 'imdb';

    const btnSrcImdb = document.getElementById("btn-src-imdb");
    const btnSrcAnime = document.getElementById("btn-src-anime");
    const btnBatchSrcImdb = document.getElementById("btn-batch-src-imdb");
    const btnBatchSrcAnime = document.getElementById("btn-batch-src-anime");

    function setSourceActive(activeBtn, inactiveBtn) {
        if (!activeBtn || !inactiveBtn) return;
        activeBtn.style.borderColor = "#38bdf8";
        activeBtn.style.background = "#2563eb";
        activeBtn.style.color = "#fff";
        inactiveBtn.style.borderColor = "rgba(255,255,255,0.15)";
        inactiveBtn.style.background = "rgba(255,255,255,0.05)";
        inactiveBtn.style.color = "#cbd5e1";
    }

    if (btnSrcImdb && btnSrcAnime) {
        btnSrcImdb.addEventListener("click", () => {
            currentSingleSource = 'imdb';
            setSourceActive(btnSrcImdb, btnSrcAnime);
            if (metaQuery && metaQuery.value.trim()) performImdbSearch(metaQuery.value.trim());
        });
        btnSrcAnime.addEventListener("click", () => {
            currentSingleSource = 'anime';
            setSourceActive(btnSrcAnime, btnSrcImdb);
            if (metaQuery && metaQuery.value.trim()) performImdbSearch(metaQuery.value.trim());
        });
    }

    if (btnBatchSrcImdb && btnBatchSrcAnime) {
        btnBatchSrcImdb.addEventListener("click", () => {
            currentBatchSource = 'imdb';
            setSourceActive(btnBatchSrcImdb, btnBatchSrcAnime);
            if (batchSeriesQuery && batchSeriesQuery.value.trim()) {
                performBatchImdbSearch(batchSeriesQuery.value.trim());
            }
        });
        btnBatchSrcAnime.addEventListener("click", () => {
            currentBatchSource = 'anime';
            setSourceActive(btnBatchSrcAnime, btnBatchSrcImdb);
            if (batchSeriesQuery && batchSeriesQuery.value.trim()) {
                performBatchImdbSearch(batchSeriesQuery.value.trim());
            }
        });
    }

    const batchSeriesQuery = document.getElementById("batch-series-query");
    const btnBatchImdbSearch = document.getElementById("btn-batch-imdb-search");
    const batchImdbSuggestions = document.getElementById("batch-imdb-suggestions");
    const batchMatchPoster = document.getElementById("batch-match-poster");
    const batchDisplayTitle = document.getElementById("batch-display-title");
    const batchDisplayYear = document.getElementById("batch-display-year");
    const batchDisplayActors = document.getElementById("batch-display-actors");
    const batchDisplayImdb = document.getElementById("batch-display-imdb");

    const batchDynamicLibraryCards = document.getElementById("batch-dynamic-library-cards");
    const batchBulkSeason = document.getElementById("batch-bulk-season");
    const btnApplyBulkSeason = document.getElementById("btn-apply-bulk-season");
    const btnAutoNumberEpisodes = document.getElementById("btn-auto-number-episodes");
    const btnSortEpisodes = document.getElementById("btn-sort-episodes");
    const batchOverwriteToggle = document.getElementById("batch-overwrite-toggle");

    const batchQueueSubtitle = document.getElementById("batch-queue-subtitle");
    const btnBatchAddFiles = document.getElementById("btn-batch-add-files");
    const btnBatchAddFolder = document.getElementById("btn-batch-add-folder");
    const btnBatchFetchTitles = document.getElementById("btn-batch-fetch-titles");
    const btnBatchClear = document.getElementById("btn-batch-clear");
    const batchEpisodesTableBody = document.getElementById("batch-episodes-table-body");

    const batchProgressBox = document.getElementById("batch-progress-box");
    const batchProgressTitle = document.getElementById("batch-progress-title");
    const batchProgressOverallPercent = document.getElementById("batch-progress-overall-percent");
    const batchProgressOverallBar = document.getElementById("batch-progress-overall-bar");
    const batchCurrentFileText = document.getElementById("batch-current-file-text");
    const batchSpeedText = document.getElementById("batch-speed-text");
    const batchEtaText = document.getElementById("batch-eta-text");
    const batchCurrentFileBar = document.getElementById("batch-current-file-bar");
    const btnStartMassIngest = document.getElementById("btn-start-mass-ingest");
    const btnStartMassText = document.getElementById("btn-start-mass-text");

    const collectionsGrid = document.getElementById("collections-grid-container");
    const collectionSearch = document.getElementById("collection-search");
    const btnSyncCollections = document.getElementById("btn-sync-collections");
    const totalCollectionsPill = document.getElementById("total-collections-pill");
    const totalOwnedPill = document.getElementById("total-owned-pill");
    const totalMissingPill = document.getElementById("total-missing-pill");

    const terminalScreen = document.getElementById("terminal-screen");
    const btnClearLogs = document.getElementById("btn-clear-logs");

    const watcherToggle = document.getElementById("watcher-master-toggle");
    const watcherStatusText = document.getElementById("watcher-status-text");
    const btnForceJellyfinRefresh = document.getElementById("btn-force-jellyfin-refresh");

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // --- Tab Switching ---
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-tab");
            tabButtons.forEach(b => b.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(targetId).classList.add("active");

            if (targetId === "queue-tab") loadIncomingQueue();
            if (targetId === "collections-tab") loadCollections();
        });
    });

    // --- Dynamic Media Directories Loader & Selector ---
    const dynamicLibraryCards = document.getElementById("dynamic-library-cards");
    const directoriesTableBody = document.getElementById("directories-table-body");
    const btnQuickCreateDir = document.getElementById("btn-quick-create-dir");
    const btnToggleCreateDirForm = document.getElementById("btn-toggle-create-dir-form");
    const createDirBox = document.getElementById("create-dir-box");
    const btnCancelCreateDir = document.getElementById("btn-cancel-create-dir");
    const btnSubmitCreateDir = document.getElementById("btn-submit-create-dir");
    const newDirName = document.getElementById("new-dir-name");
    const newDirType = document.getElementById("new-dir-type");
    const newDirAddJf = document.getElementById("new-dir-add-jf");

    let mediaDirectories = [];

    async function loadMediaDirectories() {
        try {
            const resp = await apiFetch("/api/directories");
            mediaDirectories = await resp.json();
            renderDynamicLibraryCards();
            renderBatchLibraryCards();
            renderDirectoriesTable();
        } catch (e) {
            console.error("Error loading directories:", e);
        }
    }

    function getDirIcon(d) {
        if (d.name.toLowerCase().includes("anime")) return "⛩️";
        if (d.type === "series" || d.name.toLowerCase().includes("series")) return "📺";
        if (d.name.toLowerCase().includes("children")) return "🧸";
        if (d.name.toLowerCase().includes("adult")) return "🔞";
        if (d.name.toLowerCase().includes("eesti")) return "🇪🇪";
        return "🎬";
    }

    function renderDynamicLibraryCards() {
        if (!dynamicLibraryCards) return;
        dynamicLibraryCards.innerHTML = "";

        if (mediaDirectories.length === 0) {
            dynamicLibraryCards.innerHTML = "<div class='empty-state'>No directories found on SSD.</div>";
            return;
        }

        mediaDirectories.forEach((d, idx) => {
            const isSelected = idx === 0;
            const icon = getDirIcon(d);

            const label = document.createElement("label");
            label.className = `radio-card ${isSelected ? 'active' : ''}`;
            label.innerHTML = `
                <input type="radio" name="target-library" value="${d.name}" data-path="${d.path}" data-type="${d.type}" ${isSelected ? 'checked' : ''}>
                <div class="radio-content">
                    <span class="radio-title">${icon} ${d.display_name}</span>
                    <span class="radio-desc">${d.path}</span>
                </div>
            `;

            label.addEventListener("click", () => {
                document.querySelectorAll("#dynamic-library-cards .radio-card").forEach(c => c.classList.remove("active"));
                label.classList.add("active");
                const radioInput = label.querySelector("input[type='radio']");
                radioInput.checked = true;

                const isSeriesTarget = d.type === "series";
                seriesInputs.classList.toggle("hidden", !isSeriesTarget);
            });

            dynamicLibraryCards.appendChild(label);
        });

        // Initialize seriesInputs visibility for first selected item
        const firstSelected = mediaDirectories[0];
        if (firstSelected) {
            seriesInputs.classList.toggle("hidden", firstSelected.type !== "series");
        }
    }

    function renderBatchLibraryCards() {
        if (!batchDynamicLibraryCards) return;
        batchDynamicLibraryCards.innerHTML = "";

        if (mediaDirectories.length === 0) {
            batchDynamicLibraryCards.innerHTML = "<div class='empty-state'>No directories found on SSD.</div>";
            return;
        }

        // Put series directories first
        const sortedDirs = [...mediaDirectories].sort((a, b) => {
            if (a.type === "series" && b.type !== "series") return -1;
            if (a.type !== "series" && b.type === "series") return 1;
            return 0;
        });

        sortedDirs.forEach((d, idx) => {
            const isSelected = idx === 0;
            const icon = getDirIcon(d);

            const label = document.createElement("label");
            label.className = `radio-card ${isSelected ? 'active' : ''}`;
            label.innerHTML = `
                <input type="radio" name="batch-target-library" value="${d.name}" data-path="${d.path}" data-type="${d.type}" ${isSelected ? 'checked' : ''}>
                <div class="radio-content">
                    <span class="radio-title">${icon} ${d.display_name}</span>
                    <span class="radio-desc">${d.path}</span>
                </div>
            `;

            label.addEventListener("click", () => {
                document.querySelectorAll("#batch-dynamic-library-cards .radio-card").forEach(c => c.classList.remove("active"));
                label.classList.add("active");
                const radioInput = label.querySelector("input[type='radio']");
                radioInput.checked = true;
            });

            batchDynamicLibraryCards.appendChild(label);
        });
    }

    function renderDirectoriesTable() {
        if (!directoriesTableBody) return;
        directoriesTableBody.innerHTML = "";

        if (mediaDirectories.length === 0) {
            directoriesTableBody.innerHTML = "<tr><td colspan='6' class='empty-state'>No media directories configured.</td></tr>";
            return;
        }

        mediaDirectories.forEach(d => {
            const tr = document.createElement("tr");
            const icon = getDirIcon(d);
            const typeLabel = d.type === "series" ? "TV Series" : "Movies";
            const jfBadge = d.in_jellyfin ? 
                "<span class='stat-tag stat-owned'>✔ Jellyfin Library</span>" : 
                "<span class='stat-tag stat-missing'>Folder Only</span>";

            const deleteAction = d.deletable ? `
                <button type="button" class="btn-secondary btn-sm btn-delete-dir" data-name="${d.name}">
                    🗑️ Delete
                </button>
            ` : `<span style="color: var(--c-muted-grey); font-size: 0.75rem;">Core Protected</span>`;

            tr.innerHTML = `
                <td><strong>${icon} ${d.display_name}</strong></td>
                <td><span class="pill ${d.type === 'series' ? 'pill-gold' : 'pill-blue'}">${typeLabel}</span></td>
                <td><code>${d.path}</code></td>
                <td>${d.item_count} items</td>
                <td>${jfBadge}</td>
                <td>${deleteAction}</td>
            `;

            directoriesTableBody.appendChild(tr);
        });

        // Attach delete listeners
        document.querySelectorAll(".btn-delete-dir").forEach(btn => {
            btn.addEventListener("click", async () => {
                const name = btn.getAttribute("data-name");
                if (confirm(`Are you sure you want to delete directory '${name}' and unlink it from Jellyfin?`)) {
                    btn.disabled = true;
                    btn.textContent = "Deleting...";
                    try {
                        const resp = await apiFetch("/api/directories/delete", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ name, remove_from_jellyfin: true, force: false })
                        });
                        const res = await resp.json();
                        if (res.success) {
                            alert(`Directory '${name}' removed successfully.`);
                            loadMediaDirectories();
                        } else {
                            if (confirm(`${res.error}\n\nDo you want to force delete this directory and all its contents?`)) {
                                const forceResp = await apiFetch("/api/directories/delete", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ name, remove_from_jellyfin: true, force: true })
                                });
                                const forceRes = await forceResp.json();
                                if (forceRes.success) {
                                    alert(`Directory '${name}' force deleted.`);
                                    loadMediaDirectories();
                                } else {
                                    alert(`Failed: ${forceRes.error}`);
                                }
                            }
                        }
                    } catch (e) {
                        alert(`Delete error: ${e.message}`);
                    } finally {
                        btn.disabled = false;
                        btn.textContent = "🗑️ Delete";
                    }
                }
            });
        });
    }

    // Quick create from Upload tab
    if (btnQuickCreateDir) {
        btnQuickCreateDir.addEventListener("click", () => {
            document.querySelector("[data-tab='settings-tab']").click();
            createDirBox.classList.remove("hidden");
            newDirName.focus();
        });
    }

    // Toggle Create Directory Form in Settings tab
    if (btnToggleCreateDirForm) {
        btnToggleCreateDirForm.addEventListener("click", () => {
            createDirBox.classList.toggle("hidden");
            if (!createDirBox.classList.contains("hidden")) newDirName.focus();
        });
    }

    if (btnCancelCreateDir) {
        btnCancelCreateDir.addEventListener("click", () => {
            createDirBox.classList.add("hidden");
            newDirName.value = "";
        });
    }

    if (btnSubmitCreateDir) {
        btnSubmitCreateDir.addEventListener("click", async () => {
            const name = newDirName.value.trim();
            if (!name) {
                alert("Please enter a directory name.");
                return;
            }

            btnSubmitCreateDir.disabled = true;
            btnSubmitCreateDir.textContent = "Creating...";

            try {
                const resp = await apiFetch("/api/directories/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name,
                        content_type: newDirType.value,
                        add_to_jellyfin: newDirAddJf.checked
                    })
                });
                const res = await resp.json();

                if (res.success) {
                    alert(`Directory '${name}' created on SSD and registered in Jellyfin!`);
                    createDirBox.classList.add("hidden");
                    newDirName.value = "";
                    loadMediaDirectories();
                } else {
                    alert(`Creation failed: ${res.error}`);
                }
            } catch (e) {
                alert(`Error creating directory: ${e.message}`);
            } finally {
                btnSubmitCreateDir.disabled = false;
                btnSubmitCreateDir.textContent = "Create on SSD";
            }
        });
    }

    // --- Mode Switching ---
    function switchToSingleMode() {
        if (btnModeSingle) btnModeSingle.classList.add("active");
        if (btnModeSeries) btnModeSeries.classList.remove("active");
        if (singleUploadView) singleUploadView.classList.remove("hidden");
        if (seriesBatchView) seriesBatchView.classList.add("hidden");
    }

    function switchToSeriesBatchMode() {
        if (btnModeSeries) btnModeSeries.classList.add("active");
        if (btnModeSingle) btnModeSingle.classList.remove("active");
        if (seriesBatchView) seriesBatchView.classList.remove("hidden");
        if (singleUploadView) singleUploadView.classList.add("hidden");
        renderBatchTable();
    }

    if (btnModeSingle) btnModeSingle.addEventListener("click", switchToSingleMode);
    if (btnModeSeries) btnModeSeries.addEventListener("click", switchToSeriesBatchMode);

    // --- Recursive File & Folder Drop Extraction ---
    async function getFilesFromDataTransfer(dataTransfer) {
        const fileList = [];
        const items = dataTransfer.items;
        
        if (items && items.length > 0 && items[0].webkitGetAsEntry) {
            const queue = [];
            for (let i = 0; i < items.length; i++) {
                const entry = items[i].webkitGetAsEntry();
                if (entry) queue.push(entry);
            }

            async function readEntry(entry) {
                if (entry.isFile) {
                    return new Promise((resolve) => {
                        entry.file((f) => { fileList.push(f); resolve(); }, () => resolve());
                    });
                } else if (entry.isDirectory) {
                    const dirReader = entry.createReader();
                    const readAllEntries = () => new Promise((resolve) => {
                        dirReader.readEntries(async (entries) => {
                            if (!entries || entries.length === 0) {
                                resolve();
                            } else {
                                for (const child of entries) {
                                    await readEntry(child);
                                }
                                await readAllEntries();
                                resolve();
                            }
                        }, () => resolve());
                    });
                    await readAllEntries();
                }
            }

            for (const entry of queue) {
                await readEntry(entry);
            }
        } else if (dataTransfer.files && dataTransfer.files.length > 0) {
            for (let i = 0; i < dataTransfer.files.length; i++) {
                fileList.push(dataTransfer.files[i]);
            }
        }
        return fileList;
    }

    // --- Drag & Drop File Upload ---
    browseBtn.addEventListener("click", () => fileInput.click());
    if (browseFolderBtn) browseFolderBtn.addEventListener("click", () => folderInput.click());
    if (folderInput) {
        folderInput.addEventListener("change", () => {
            if (folderInput.files && folderInput.files.length > 0) {
                switchToSeriesBatchMode();
                addFilesToBatch(Array.from(folderInput.files));
                folderInput.value = "";
            }
        });
    }

    dropZone.addEventListener("click", (e) => {
        if (e.target !== browseBtn && e.target !== browseFolderBtn) fileInput.click();
    });

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove("dragover");
        });
    });

    dropZone.addEventListener("drop", async (e) => {
        const files = await getFilesFromDataTransfer(e.dataTransfer);
        if (files && files.length > 0) {
            if (files.length > 1 || (btnModeSeries && btnModeSeries.classList.contains("active"))) {
                switchToSeriesBatchMode();
                addFilesToBatch(files);
            } else {
                handleFileUpload(files[0]);
            }
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files.length > 0) {
            if (fileInput.files.length > 1 || (btnModeSeries && btnModeSeries.classList.contains("active"))) {
                switchToSeriesBatchMode();
                addFilesToBatch(Array.from(fileInput.files));
            } else {
                handleFileUpload(fileInput.files[0]);
            }
            fileInput.value = "";
        }
    });

    // Batch mode drop zone
    if (batchDropZone) {
        batchDropZone.addEventListener("click", () => fileInput.click());
        ["dragenter", "dragover"].forEach(eventName => {
            batchDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                batchDropZone.classList.add("dragover");
            });
        });
        ["dragleave", "drop"].forEach(eventName => {
            batchDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                batchDropZone.classList.remove("dragover");
            });
        });
        batchDropZone.addEventListener("drop", async (e) => {
            const files = await getFilesFromDataTransfer(e.dataTransfer);
            if (files && files.length > 0) {
                addFilesToBatch(files);
            }
        });
    }

    if (btnBatchAddFiles) btnBatchAddFiles.addEventListener("click", () => fileInput.click());
    if (btnBatchAddFolder) btnBatchAddFolder.addEventListener("click", () => folderInput.click());
    if (btnBatchClear) {
        btnBatchClear.addEventListener("click", () => {
            if (isBatchProcessing) return;
            if (batchQueue.length > 0 && confirm("Are you sure you want to clear the series queue?")) {
                batchQueue = [];
                renderBatchTable();
            }
        });
    }

    const CHUNK_SIZE = 64 * 1024 * 1024; // 64 MB chunks (safely within Cloudflare 100MB body limit)
    const MAX_CONCURRENT_CHUNKS = 4;     // 4 parallel streams to saturate bandwidth and defeat single-stream throttling

    async function uploadFileChunked(file, onProgress) {
        const totalSize = file.size;
        const totalChunks = Math.max(1, Math.ceil(totalSize / CHUNK_SIZE));
        const uploadId = 'up_' + Date.now() + '_' + Math.random().toString(36).substr(2, 8);
        const startTime = Date.now();

        // Track loaded bytes per chunk for real-time smooth aggregated progress calculation
        const chunkLoadedBytes = new Array(totalChunks).fill(0);
        let finalResult = null;

        const updateAggregatedProgress = () => {
            if (!onProgress) return;
            const curTotalLoaded = chunkLoadedBytes.reduce((a, b) => a + b, 0);
            const percent = Math.min(99, Math.round((curTotalLoaded / totalSize) * 100));
            const elapsed = (Date.now() - startTime) / 1000;
            const speedBps = elapsed > 0 ? curTotalLoaded / elapsed : 0;
            const speedMBps = (speedBps / (1024 * 1024)).toFixed(1);
            const remainingSecs = speedBps > 0 ? Math.round((totalSize - curTotalLoaded) / speedBps) : 0;
            onProgress(percent, speedMBps, remainingSecs);
        };

        const uploadSingleChunk = async (chunkIdx) => {
            const start = chunkIdx * CHUNK_SIZE;
            const end = Math.min(totalSize, start + CHUNK_SIZE);
            const chunkSize = end - start;
            const chunkBlob = file.slice(start, end);

            let lastErr = null;
            for (let attempt = 1; attempt <= 3; attempt++) {
                try {
                    const formData = new FormData();
                    formData.append("upload_id", uploadId);
                    formData.append("chunk_index", chunkIdx.toString());
                    formData.append("total_chunks", totalChunks.toString());
                    formData.append("filename", file.name);
                    formData.append("chunk", chunkBlob, file.name);

                    const chunkResult = await new Promise((resolve, reject) => {
                        const xhr = new XMLHttpRequest();
                        xhr.upload.addEventListener("progress", (e) => {
                            if (e.lengthComputable) {
                                chunkLoadedBytes[chunkIdx] = e.loaded;
                                updateAggregatedProgress();
                            }
                        });

                        xhr.onreadystatechange = () => {
                            if (xhr.readyState === XMLHttpRequest.DONE) {
                                if (xhr.status === 200) {
                                    try {
                                        resolve(JSON.parse(xhr.responseText));
                                    } catch (err) {
                                        reject(new Error("Invalid response from server: " + xhr.responseText.slice(0, 100)));
                                    }
                                } else if (xhr.status === 401) {
                                    showLoginModal("Session expired. Please log in again.");
                                    reject(new Error("Unauthorized: Please sign in as Jellyfin Admin"));
                                } else if (xhr.status === 413) {
                                    reject(new Error("Payload too large (HTTP 413)"));
                                } else {
                                    reject(new Error(`Upload failed (HTTP ${xhr.status})`));
                                }
                            }
                        };

                        xhr.onerror = () => reject(new Error("Network connection error during chunk upload"));
                        xhr.open("POST", apiUrl("/api/upload-chunk"), true);
                        xhr.send(formData);
                    });

                    chunkLoadedBytes[chunkIdx] = chunkSize;
                    updateAggregatedProgress();

                    if (chunkResult && chunkResult.completed) {
                        finalResult = chunkResult;
                    }
                    return;
                } catch (err) {
                    lastErr = err;
                    if (err.message && err.message.includes("Unauthorized")) throw err;
                    console.warn(`Chunk ${chunkIdx + 1}/${totalChunks} attempt ${attempt} failed:`, err);
                    if (attempt < 3) {
                        await new Promise(r => setTimeout(r, 1500 * attempt));
                    }
                }
            }
            throw new Error(`Chunk ${chunkIdx + 1}/${totalChunks} failed: ${lastErr?.message || "Unknown error"}`);
        };

        // Worker queue for parallel chunk uploads
        let nextChunkIdx = 0;
        let workerError = null;

        const worker = async () => {
            while (nextChunkIdx < totalChunks && !workerError) {
                const chunkIdx = nextChunkIdx++;
                try {
                    await uploadSingleChunk(chunkIdx);
                } catch (err) {
                    workerError = err;
                    throw err;
                }
            }
        };

        const concurrency = Math.min(MAX_CONCURRENT_CHUNKS, totalChunks);
        const workers = Array.from({ length: concurrency }, () => worker());
        await Promise.all(workers);

        if (finalResult && finalResult.completed) {
            if (onProgress) onProgress(100, "0.0", 0);
            return finalResult.temp_path;
        }

        throw new Error("All chunks uploaded but server did not complete file reassembly.");
    }

    async function handleFileUpload(file) {
        uploadProgressBox.classList.remove("hidden");
        uploadFileName.textContent = `Uploading: ${file.name}`;
        uploadPercent.textContent = "0%";
        uploadProgressBar.style.width = "0%";
        btnProcessIngest.disabled = true;

        try {
            const tempPath = await uploadFileChunked(file, (percent, speed, eta) => {
                uploadPercent.textContent = `${percent}%`;
                uploadProgressBar.style.width = `${percent}%`;
                uploadSpeed.textContent = `${speed} MB/s`;
                uploadEta.textContent = `ETA: ${eta}s`;
            });

            currentUploadedPath = tempPath;
            uploadPercent.textContent = "100% (Complete)";
            uploadProgressBar.style.width = "100%";
            btnProcessIngest.disabled = false;
            autoInspectUploadedFile(file.name);
        } catch (err) {
            console.error("Upload error:", err);
            alert(`Upload failed: ${err.message}`);
            uploadProgressBox.classList.add("hidden");
        }
    }

    // --- Title Cleaning & Metadata Suggestion ---
    async function autoInspectUploadedFile(filename) {
        try {
            const resp = await apiFetch("/api/clean-title", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename })
            });
            const data = await resp.json();
            
            metaQuery.value = data.cleaned_title;
            if (data.is_series) {
                // Switch radio to series
                document.querySelector("input[value='series']").checked = true;
                radioCards.forEach(c => c.classList.remove("active"));
                document.querySelector("input[value='series']").closest(".radio-card").classList.add("active");
                seriesInputs.classList.remove("hidden");
                if (data.season) seriesSeason.value = data.season;
                if (data.episode) seriesEpisode.value = data.episode;
            }

            // Search IMDb
            performImdbSearch(data.cleaned_title);
        } catch (e) {
            console.error("Auto inspect error:", e);
        }
    }

    btnImdbSearch.addEventListener("click", () => {
        performImdbSearch(metaQuery.value);
    });

    metaQuery.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            performImdbSearch(metaQuery.value);
        }
    });

    async function performImdbSearch(query) {
        if (!query || query.trim() === "") return;
        const source = currentSingleSource || "imdb";
        const label = source === "anime" ? "Anime DB (Kitsu)" : "IMDb";
        imdbSuggestionsList.innerHTML = `<div class='suggestion-item'>Searching ${label}...</div>`;
        imdbSuggestionsList.classList.remove("hidden");

        try {
            const resp = await apiFetch(`/api/search?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`);
            const results = await resp.json();

            if (results.length === 0) {
                imdbSuggestionsList.innerHTML = `<div class='suggestion-item'>No ${label} results found. Using fallback query.</div>`;
                setFallbackMetadata(query);
                return;
            }

            imdbSuggestionsList.innerHTML = "";
            results.forEach((item, index) => {
                const div = document.createElement("div");
                div.className = "suggestion-item";
                div.innerHTML = `
                    <img src="${item.poster || '/static/img/no-poster.png'}" class="suggestion-thumb" alt="poster" onerror="this.src='/static/img/no-poster.png'">
                    <div>
                        <div class="suggestion-title">${item.title} (${item.year})</div>
                        <div class="suggestion-meta">${item.actors} • ${item.imdb_id}</div>
                    </div>
                `;
                div.addEventListener("click", () => {
                    selectMetadata(item);
                    imdbSuggestionsList.classList.add("hidden");
                });
                imdbSuggestionsList.appendChild(div);

                // Default to top result
                if (index === 0) selectMetadata(item);
            });
        } catch (e) {
            console.error("IMDb search error:", e);
            imdbSuggestionsList.classList.add("hidden");
        }
    }

    function selectMetadata(item) {
        selectedMetadata = item;
        displayTitle.textContent = item.title;
        displayYear.textContent = item.year || "Year";
        displayActors.textContent = item.actors || "Cast info not available";
        displayImdbId.textContent = item.imdb_id || "tt-------";
        
        if (item.poster) {
            matchPoster.innerHTML = `<img src="${item.poster}" alt="${item.title}">`;
        } else {
            matchPoster.innerHTML = `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>`;
        }

        if (item.type === "movie") {
            seriesInputs.classList.add("hidden");
        } else if (item.type === "series" && currentSingleSource === "anime") {
            seriesInputs.classList.remove("hidden");
        }

        btnProcessIngest.disabled = false;
    }

    function setFallbackMetadata(title) {
        selectedMetadata = {
            title: title,
            year: new Date().getFullYear().toString(),
            imdb_id: null,
            actors: "Custom user entered title"
        };
        displayTitle.textContent = title;
        displayYear.textContent = selectedMetadata.year;
        displayActors.textContent = selectedMetadata.actors;
        displayImdbId.textContent = "manual";
        btnProcessIngest.disabled = false;
    }

    // --- Process & Ingest Button Action ---
    btnProcessIngest.addEventListener("click", async () => {
        if (!currentUploadedPath) {
            alert("Please upload or select a media file first!");
            return;
        }

        const selectedRadio = document.querySelector("input[name='target-library']:checked");
        let targetCategory = selectedRadio ? (selectedRadio.getAttribute("data-type") || "movies") : "movies";
        const selectedValue = selectedRadio ? selectedRadio.value : "";
        const targetPath = selectedRadio ? selectedRadio.getAttribute("data-path") : null;
        if (selectedValue === "Anime" || (targetPath && targetPath.toLowerCase().includes("anime"))) {
            targetCategory = "anime";
        }

        const isSeries = targetCategory === "series" || (targetCategory === "anime" && !seriesInputs.classList.contains("hidden"));

        const payload = {
            src_file: currentUploadedPath,
            target_category: targetCategory,
            custom_dir: targetPath,
            title: selectedMetadata ? selectedMetadata.title : metaQuery.value,
            year: selectedMetadata ? selectedMetadata.year : null,
            imdb_id: selectedMetadata ? selectedMetadata.imdb_id : null,
            season: isSeries ? parseInt(seriesSeason.value) : null,
            episode: isSeries ? parseInt(seriesEpisode.value) : null,
            episode_title: isSeries ? seriesEpTitle.value : null,
            overwrite: overwriteToggle.checked
        };

        btnProcessIngest.disabled = true;
        btnProcessIngest.innerHTML = "<span>Ingesting into Media Storage...</span>";

        try {
            const resp = await apiFetch("/api/process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const res = await resp.json();

            if (res.success) {
                alert(`Successfully ingested '${res.title}' into Media Storage!`);
                currentUploadedPath = null;
                uploadProgressBox.classList.add("hidden");
                // Switch to Live Console
                document.querySelector("[data-tab='logs-tab']").click();
            } else {
                alert(`Ingestion failed: ${res.error}`);
            }
        } catch (e) {
            alert(`Error: ${e.message}`);
        } finally {
            btnProcessIngest.disabled = false;
            btnProcessIngest.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                <span>Tag & Ingest Media</span>
            `;
        }
    });

    // ==========================================================
    // MASS SERIES INGESTION IMPLEMENTATION
    // ==========================================================

    function renderBatchTable() {
        if (!batchEpisodesTableBody) return;
        batchEpisodesTableBody.innerHTML = "";

        if (batchQueue.length === 0) {
            batchEpisodesTableBody.innerHTML = `<tr><td colspan="8" class="empty-state">No episodes added yet. Drag & drop files or a folder above.</td></tr>`;
            batchQueueSubtitle.textContent = `0 episodes loaded • 0 MB total`;
            seriesBatchBadge.classList.add("hidden");
            btnStartMassIngest.disabled = true;
            return;
        }

        seriesBatchBadge.textContent = batchQueue.length;
        seriesBatchBadge.classList.remove("hidden");

        const totalMB = batchQueue.reduce((acc, it) => acc + (it.size_mb || 0), 0);
        const sizeStr = totalMB > 1024 ? `${(totalMB / 1024).toFixed(2)} GB` : `${Math.round(totalMB)} MB`;
        batchQueueSubtitle.textContent = `${batchQueue.length} episode${batchQueue.length === 1 ? '' : 's'} loaded • ${sizeStr} total`;

        btnStartMassIngest.disabled = isBatchProcessing;

        batchQueue.forEach((item, idx) => {
            const tr = document.createElement("tr");
            tr.id = `batch-row-${item.id}`;

            let statusBadge = `<span class="stat-tag stat-missing">Queued</span>`;
            if (item.status === "uploading") {
                statusBadge = `<span class="stat-tag stat-uploading">${item.status_text || 'Uploading...'}</span>`;
            } else if (item.status === "ingesting") {
                statusBadge = `<span class="stat-tag stat-ingesting">Tagging & Ingesting</span>`;
            } else if (item.status === "done") {
                statusBadge = `<span class="stat-tag stat-owned">✔ Ingested</span>`;
            } else if (item.status === "error") {
                statusBadge = `<span class="stat-tag" style="background: rgba(244,63,94,0.2); color:#fda4af; border:1px solid #f43f5e;">✖ Error</span>`;
            }

            const sourceBadge = item.is_server_file ? `<span title="Located on Server in Watch Directory" style="font-size:0.75rem; color:var(--c-golden); margin-left:4px; font-weight:600;">[Server]</span>` : '';

            tr.innerHTML = `
                <td><strong>${idx + 1}</strong></td>
                <td><code>${escapeHtml(item.name)}</code>${sourceBadge}</td>
                <td>
                    <input type="number" class="text-input batch-input-num" min="1" value="${item.season}" 
                        onchange="updateBatchItem('${item.id}', 'season', parseInt(this.value) || 1)">
                </td>
                <td>
                    <input type="number" class="text-input batch-input-num" min="1" value="${item.episode}" 
                        onchange="updateBatchItem('${item.id}', 'episode', parseInt(this.value) || 1)">
                </td>
                <td>
                    <input type="text" class="text-input batch-input-title" placeholder="Episode Title (optional)" value="${escapeHtml(item.episode_title || '')}"
                        onchange="updateBatchItem('${item.id}', 'episode_title', this.value.trim())">
                </td>
                <td>${item.size_mb > 1024 ? (item.size_mb / 1024).toFixed(1) + ' GB' : Math.round(item.size_mb) + ' MB'}</td>
                <td class="row-status">${statusBadge}</td>
                <td>
                    <button type="button" class="btn-delete-row" title="Remove from batch" onclick="removeBatchItem('${item.id}')">🗑️</button>
                </td>
            `;

            batchEpisodesTableBody.appendChild(tr);
        });
    }

    window.updateBatchItem = (id, key, val) => {
        const it = batchQueue.find(x => x.id === id);
        if (it) {
            it[key] = val;
        }
    };

    window.removeBatchItem = (id) => {
        if (isBatchProcessing) return;
        batchQueue = batchQueue.filter(x => x.id !== id);
        renderBatchTable();
    };

    async function addFilesToBatch(fileList) {
        const videoExts = [".mp4", ".mkv", ".avi", ".mov"];
        const validFiles = fileList.filter(f => {
            const lower = f.name.toLowerCase();
            return videoExts.some(ext => lower.endsWith(ext)) && !f.name.startsWith(".");
        });

        if (validFiles.length === 0) {
            alert("No valid video files (.mp4, .mkv, .avi, .mov) found.");
            return;
        }

        let cleanedMetas = [];
        try {
            const resp = await apiFetch("/api/batch-clean-titles", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filenames: validFiles.map(f => f.name) })
            });
            cleanedMetas = await resp.json();
        } catch (e) {
            console.error("Batch clean error:", e);
        }

        let firstGuessedShow = null;
        let firstGuessedYear = null;

        validFiles.forEach((file, idx) => {
            const meta = cleanedMetas[idx] || {};
            const szMb = file.size ? file.size / (1024 * 1024) : 0;
            const itemId = 'bf_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);

            if (!firstGuessedShow && (meta.series_show_name || meta.cleaned_title)) {
                firstGuessedShow = meta.series_show_name || meta.cleaned_title;
                firstGuessedYear = meta.guessed_year;
            }

            batchQueue.push({
                id: itemId,
                file: file,
                server_path: null,
                is_server_file: false,
                name: file.name,
                size_mb: szMb,
                season: meta.season || 1,
                episode: meta.episode || (batchQueue.length + 1),
                episode_title: meta.episode_title || "",
                status: "queued",
                status_text: "Queued",
                error_msg: null
            });
        });

        // Match against cached episode titles if already loaded
        if (cachedSeriesEpisodes.length > 0) {
            batchQueue.forEach(item => {
                if (!item.episode_title) {
                    const match = cachedSeriesEpisodes.find(ep => ep.season === item.season && ep.episode === item.episode);
                    if (match && match.title) {
                        item.episode_title = match.title;
                    }
                }
            });
        }

        // Auto-sort batch by season and episode
        batchQueue.sort((a, b) => (a.season * 1000 + a.episode) - (b.season * 1000 + b.episode));

        renderBatchTable();

        // Auto-select Anime library if appropriate
        if (firstGuessedShow) {
            const showLower = firstGuessedShow.toLowerCase();
            if (showLower.includes("frieren") || showLower.includes("anime") || showLower.includes("sousou")) {
                const animeRadio = document.querySelector("input[name='batch-target-library'][value='Anime']");
                if (animeRadio) {
                    document.querySelectorAll("#batch-dynamic-library-cards .radio-card").forEach(c => c.classList.remove("active"));
                    animeRadio.checked = true;
                    const parentLabel = animeRadio.closest(".radio-card");
                    if (parentLabel) parentLabel.classList.add("active");
                }
            }
        }

        // If series title search is empty, auto-populate and search IMDb
        if (firstGuessedShow && !batchSelectedMetadata && !batchSeriesQuery.value.trim()) {
            batchSeriesQuery.value = firstGuessedShow;
            performBatchImdbSearch(firstGuessedShow, firstGuessedYear);
            loadSeriesEpisodes(firstGuessedShow);
        }
    }

    function addServerFilesToBatch(files) {
        if (!files || files.length === 0) return;

        let firstGuessedShow = null;
        let firstGuessedYear = null;

        files.forEach(f => {
            const itemId = 'bf_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
            if (!firstGuessedShow && (f.series_show_name || f.cleaned_title)) {
                firstGuessedShow = f.series_show_name || f.cleaned_title;
                firstGuessedYear = f.guessed_year;
            }

            batchQueue.push({
                id: itemId,
                file: null,
                server_path: f.path,
                is_server_file: true,
                name: f.filename,
                size_mb: f.size_mb || 0,
                season: f.season || 1,
                episode: f.episode || (batchQueue.length + 1),
                episode_title: f.episode_title || "",
                status: "queued",
                status_text: "Queued",
                error_msg: null
            });
        });

        // Match against cached episode titles if already loaded
        if (cachedSeriesEpisodes.length > 0) {
            batchQueue.forEach(item => {
                if (!item.episode_title) {
                    const match = cachedSeriesEpisodes.find(ep => ep.season === item.season && ep.episode === item.episode);
                    if (match && match.title) {
                        item.episode_title = match.title;
                    }
                }
            });
        }

        batchQueue.sort((a, b) => (a.season * 1000 + a.episode) - (b.season * 1000 + b.episode));
        renderBatchTable();

        if (firstGuessedShow) {
            const showLower = firstGuessedShow.toLowerCase();
            if (showLower.includes("frieren") || showLower.includes("anime") || showLower.includes("sousou")) {
                const animeRadio = document.querySelector("input[name='batch-target-library'][value='Anime']");
                if (animeRadio) {
                    document.querySelectorAll("#batch-dynamic-library-cards .radio-card").forEach(c => c.classList.remove("active"));
                    animeRadio.checked = true;
                    const parentLabel = animeRadio.closest(".radio-card");
                    if (parentLabel) parentLabel.classList.add("active");
                }
            }
        }

        if (firstGuessedShow && !batchSelectedMetadata && !batchSeriesQuery.value.trim()) {
            batchSeriesQuery.value = firstGuessedShow;
            performBatchImdbSearch(firstGuessedShow, firstGuessedYear);
            loadSeriesEpisodes(firstGuessedShow);
        }
    }

    // Series IMDb Search in Batch Mode
    if (btnBatchImdbSearch) {
        btnBatchImdbSearch.addEventListener("click", () => {
            performBatchImdbSearch(batchSeriesQuery.value.trim());
        });
    }

    if (batchSeriesQuery) {
        batchSeriesQuery.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                performBatchImdbSearch(batchSeriesQuery.value.trim());
            }
        });
    }

    async function performBatchImdbSearch(query, preferredYear) {
        if (!query || !query.trim()) return;
        const source = currentBatchSource || "imdb";
        const label = source === "anime" ? "Anime DB (Kitsu)" : "IMDb";
        batchImdbSuggestions.innerHTML = `<div class='suggestion-item loading'>Searching ${label}...</div>`;
        batchImdbSuggestions.classList.remove("hidden");

        try {
            const resp = await apiFetch(`/api/search?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`);
            const results = await resp.json();

            batchImdbSuggestions.innerHTML = "";
            if (!results || results.length === 0) {
                batchImdbSuggestions.innerHTML = "<div class='suggestion-item'>No IMDb results found. Using custom title.</div>";
                setTimeout(() => batchImdbSuggestions.classList.add("hidden"), 2500);
                setFallbackBatchMetadata(query);
                return;
            }

            // Prioritize series results
            results.sort((a, b) => {
                if (a.type === "series" && b.type !== "series") return -1;
                if (a.type !== "series" && b.type === "series") return 1;
                return 0;
            });

            // If preferredYear matches first result, auto-select!
            const exactMatch = preferredYear ? results.find(r => r.year === preferredYear) : null;
            if (exactMatch && !batchSelectedMetadata) {
                selectBatchMetadata(exactMatch);
                batchImdbSuggestions.classList.add("hidden");
                return;
            }

            results.slice(0, 5).forEach(item => {
                const div = document.createElement("div");
                div.className = "suggestion-item";
                const posterImg = item.poster ? `<img src="${item.poster}" class="sug-poster" alt="poster">` : `<div class="sug-poster-empty">📺</div>`;
                div.innerHTML = `
                    ${posterImg}
                    <div class="sug-info">
                        <span class="sug-title">${escapeHtml(item.title)}</span>
                        <span class="sug-meta">${item.year} • ${item.type === 'series' ? 'TV Series' : 'Movie'} • ${escapeHtml(item.actors || '')}</span>
                    </div>
                `;
                div.addEventListener("click", () => {
                    selectBatchMetadata(item);
                    batchImdbSuggestions.classList.add("hidden");
                });
                batchImdbSuggestions.appendChild(div);
            });
        } catch (e) {
            console.error("Batch IMDb search error:", e);
            batchImdbSuggestions.classList.add("hidden");
        }
    }

    function selectBatchMetadata(item) {
        batchSelectedMetadata = item;
        batchSeriesQuery.value = item.title;
        batchDisplayTitle.textContent = item.title;
        batchDisplayYear.textContent = item.year;
        batchDisplayActors.textContent = item.actors || "TV Series";
        batchDisplayImdb.textContent = item.imdb_id || "tt-------";

        if (item.poster) {
            batchMatchPoster.innerHTML = `<img src="${item.poster}" alt="${item.title}">`;
        } else {
            batchMatchPoster.innerHTML = `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/></svg>`;
        }

        loadSeriesEpisodes(item.title, item.imdb_id);
    }

    function setFallbackBatchMetadata(title) {
        batchSelectedMetadata = {
            title: title,
            year: new Date().getFullYear().toString(),
            imdb_id: null,
            actors: "Custom series title"
        };
        batchDisplayTitle.textContent = title;
        batchDisplayYear.textContent = batchSelectedMetadata.year;
        batchDisplayActors.textContent = batchSelectedMetadata.actors;
        batchDisplayImdb.textContent = "manual";

        loadSeriesEpisodes(title, null);
    }

    async function loadSeriesEpisodes(seriesTitle, imdbId = null) {
        if (!seriesTitle) return;
        try {
            const source = currentBatchSource || (imdbId && imdbId.startsWith("kitsu-") ? "anime" : "imdb");
            const url = apiUrl(`/api/series-episodes?q=${encodeURIComponent(seriesTitle)}&imdb_id=${encodeURIComponent(imdbId || '')}&source=${encodeURIComponent(source)}`);
            const res = await apiFetch(url);
            const data = await res.json();
            if (data && data.episodes && data.episodes.length > 0) {
                cachedSeriesEpisodes = data.episodes;
                console.log(`Loaded ${data.episodes.length} episodes for ${data.show || seriesTitle}`);
                applyEpisodeTitlesToQueue(true);
            }
        } catch (err) {
            console.warn("Failed to fetch episode guide:", err);
        }
    }

    function autoFillEpisodeTitles(silent = false) {
        if (batchQueue.length === 0) {
            if (!silent) alert("Please add episodes to the queue first.");
            return;
        }

        const seriesTitle = batchSelectedMetadata ? batchSelectedMetadata.title : batchSeriesQuery.value.trim();
        const imdbId = batchSelectedMetadata ? batchSelectedMetadata.imdb_id : null;

        if (cachedSeriesEpisodes.length === 0) {
            if (seriesTitle) {
                if (!silent && btnBatchFetchTitles) {
                    btnBatchFetchTitles.disabled = true;
                    btnBatchFetchTitles.textContent = "Fetching...";
                }
                loadSeriesEpisodes(seriesTitle, imdbId).then(() => {
                    if (btnBatchFetchTitles) {
                        btnBatchFetchTitles.disabled = false;
                        btnBatchFetchTitles.textContent = "✨ Auto-Fill Episode Names";
                    }
                    if (cachedSeriesEpisodes.length > 0) {
                        applyEpisodeTitlesToQueue(silent);
                    } else if (!silent) {
                        alert("Could not find official episode titles for: " + seriesTitle);
                    }
                });
            } else if (!silent) {
                alert("Please enter or search for a Series Title first!");
                batchSeriesQuery.focus();
            }
            return;
        }

        applyEpisodeTitlesToQueue(silent);
    }

    function applyEpisodeTitlesToQueue(silent = false) {
        let updatedCount = 0;
        batchQueue.forEach(item => {
            const match = cachedSeriesEpisodes.find(ep => ep.season === item.season && ep.episode === item.episode);
            if (match && match.title) {
                item.episode_title = match.title;
                updatedCount++;
            }
        });

        renderBatchTable();
        if (!silent) {
            alert(`✨ Auto-filled ${updatedCount} episode titles from the official guide!`);
        }
    }

    if (btnBatchFetchTitles) {
        btnBatchFetchTitles.addEventListener("click", () => {
            autoFillEpisodeTitles(false);
        });
    }

    // Bulk Tools (Renumbering, Sorting, Season Apply)
    if (btnApplyBulkSeason) {
        btnApplyBulkSeason.addEventListener("click", () => {
            const seasonVal = parseInt(batchBulkSeason.value) || 1;
            batchQueue.forEach(it => it.season = seasonVal);
            renderBatchTable();
        });
    }

    if (btnAutoNumberEpisodes) {
        btnAutoNumberEpisodes.addEventListener("click", () => {
            batchQueue.forEach((it, idx) => it.episode = idx + 1);
            renderBatchTable();
        });
    }

    if (btnSortEpisodes) {
        btnSortEpisodes.addEventListener("click", () => {
            batchQueue.sort((a, b) => (a.season * 1000 + a.episode) - (b.season * 1000 + b.episode));
            renderBatchTable();
        });
    }

    // Mass Ingest Execution
    if (btnStartMassIngest) {
        btnStartMassIngest.addEventListener("click", startMassIngest);
    }

    async function startMassIngest() {
        if (batchQueue.length === 0 || isBatchProcessing) return;

        const seriesTitle = batchSelectedMetadata ? batchSelectedMetadata.title : batchSeriesQuery.value.trim();
        if (!seriesTitle) {
            alert("Please provide or search for a Series Title before starting ingest!");
            batchSeriesQuery.focus();
            return;
        }

        const selectedRadio = document.querySelector("input[name='batch-target-library']:checked");
        const targetPath = selectedRadio ? selectedRadio.getAttribute("data-path") : null;
        const overwrite = batchOverwriteToggle ? batchOverwriteToggle.checked : true;

        isBatchProcessing = true;
        btnStartMassIngest.disabled = true;
        if (btnBatchClear) btnBatchClear.disabled = true;
        if (btnBatchAddFiles) btnBatchAddFiles.disabled = true;
        if (btnBatchAddFolder) btnBatchAddFolder.disabled = true;

        batchProgressBox.classList.remove("hidden");
        batchProgressOverallPercent.textContent = "0%";
        batchProgressOverallBar.style.width = "0%";

        const totalItems = batchQueue.length;
        let completedCount = 0;
        let failCount = 0;

        for (let i = 0; i < totalItems; i++) {
            const item = batchQueue[i];
            if (item.status === "done") {
                completedCount++;
                continue;
            }

            batchProgressTitle.textContent = `Ingesting Episode ${i + 1} of ${totalItems}: ${item.name}`;
            batchCurrentFileText.textContent = `Preparing: ${item.name}`;

            const row = document.getElementById(`batch-row-${item.id}`);
            const statusCell = row ? row.querySelector(".row-status") : null;

            let srcFilePath = item.server_path;

            // Step 1: Upload if not already on server
            if (!item.is_server_file && item.file) {
                item.status = "uploading";
                if (statusCell) statusCell.innerHTML = `<span class="stat-tag stat-uploading">Uploading 0%</span>`;

                try {
                    srcFilePath = await uploadSingleFileWithProgress(item.file, (percent, speedMBps, etaSecs) => {
                        if (statusCell) statusCell.innerHTML = `<span class="stat-tag stat-uploading">${percent}%</span>`;
                        batchCurrentFileBar.style.width = `${percent}%`;
                        batchSpeedText.textContent = `${speedMBps} MB/s`;
                        batchEtaText.textContent = `ETA: ${etaSecs}s`;
                    });
                } catch (err) {
                    item.status = "error";
                    item.error_msg = err.message;
                    if (statusCell) statusCell.innerHTML = `<span class="stat-tag" style="background: rgba(244,63,94,0.2); color:#fda4af;">Upload Failed</span>`;
                    failCount++;
                    continue;
                }
            }

            // Step 2: Tag metadata & Ingest
            item.status = "ingesting";
            if (statusCell) statusCell.innerHTML = `<span class="stat-tag stat-ingesting">Tagging...</span>`;
            batchCurrentFileText.textContent = `Tagging metadata & moving to media storage...`;
            batchCurrentFileBar.style.width = `100%`;

            try {
                const processResp = await apiFetch("/api/process", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        src_file: srcFilePath,
                        target_category: "series",
                        custom_dir: targetPath,
                        title: seriesTitle,
                        year: batchSelectedMetadata ? batchSelectedMetadata.year : null,
                        imdb_id: batchSelectedMetadata ? batchSelectedMetadata.imdb_id : null,
                        season: item.season,
                        episode: item.episode,
                        episode_title: item.episode_title || null,
                        overwrite: overwrite
                    })
                });
                const res = await processResp.json();
                if (res.success) {
                    item.status = "done";
                    if (statusCell) statusCell.innerHTML = `<span class="stat-tag stat-owned">✔ Ingested</span>`;
                    completedCount++;
                } else {
                    item.status = "error";
                    item.error_msg = res.error;
                    if (statusCell) statusCell.innerHTML = `<span class="stat-tag" style="background: rgba(244,63,94,0.2); color:#fda4af;">Ingest Error</span>`;
                    failCount++;
                }
            } catch (err) {
                item.status = "error";
                item.error_msg = err.message;
                if (statusCell) statusCell.innerHTML = `<span class="stat-tag" style="background: rgba(244,63,94,0.2); color:#fda4af;">Error</span>`;
                failCount++;
            }

            const overallPct = Math.round(((i + 1) / totalItems) * 100);
            batchProgressOverallPercent.textContent = `${overallPct}%`;
            batchProgressOverallBar.style.width = `${overallPct}%`;
        }

        // Step 3: Trigger Jellyfin Library Refresh
        batchCurrentFileText.textContent = `Triggering Library Scan...`;
        try {
            await apiFetch("/api/refresh-library", { method: "POST" });
        } catch (e) {
            console.error("Library refresh trigger error:", e);
        }

        isBatchProcessing = false;
        btnStartMassIngest.disabled = false;
        if (btnBatchClear) btnBatchClear.disabled = false;
        if (btnBatchAddFiles) btnBatchAddFiles.disabled = false;
        if (btnBatchAddFolder) btnBatchAddFolder.disabled = false;

        batchProgressTitle.textContent = `Batch Ingest Finished (${completedCount} succeeded, ${failCount} failed)`;
        batchCurrentFileText.textContent = `All episodes organized in media storage and library refresh triggered.`;
        batchSpeedText.textContent = "";
        batchEtaText.textContent = "";

        alert(`🎉 Batch ingest complete!\n${completedCount} episodes of '${seriesTitle}' successfully ingested to media storage.`);
    }

    function uploadSingleFileWithProgress(file, onProgress) {
        return uploadFileChunked(file, onProgress);
    }

    // --- Tab 2: Incoming Queue ---
    btnRefreshQueue.addEventListener("click", loadIncomingQueue);

    async function loadIncomingQueue() {
        try {
            const resp = await apiFetch("/api/incoming");
            const files = await resp.json();
            incomingQueueFiles = files;

            queueBadge.textContent = files.length;
            if (files.length === 0) {
                queueTableBody.innerHTML = `<tr><td colspan="6" class="empty-state">No files currently in incoming directory.</td></tr>`;
                if (btnBatchSeriesQueue) btnBatchSeriesQueue.disabled = true;
                if (queueSelectAll) queueSelectAll.checked = false;
                return;
            }

            queueTableBody.innerHTML = "";
            files.forEach((f, idx) => {
                const tr = document.createElement("tr");
                const statusBadge = f.is_ready ? 
                    `<span class="stat-tag stat-owned">Ready</span>` : 
                    `<span class="stat-tag stat-missing">Downloading...</span>`;

                tr.innerHTML = `
                    <td><input type="checkbox" class="queue-item-cb" data-idx="${idx}" ${!f.is_ready ? 'disabled' : ''}></td>
                    <td><code>${escapeHtml(f.filename)}</code></td>
                    <td><strong>${escapeHtml(f.cleaned_title)}</strong> ${f.guessed_year ? `(${f.guessed_year})` : ''}</td>
                    <td>${f.size_mb} MB</td>
                    <td>${statusBadge}</td>
                    <td>
                        <button class="btn-secondary btn-sm" ${!f.is_ready ? 'disabled' : ''} onclick="queueIngestFile('${f.path.replace(/'/g, "\\'")}', '${f.cleaned_title.replace(/'/g, "\\'")}')">
                            Ingest
                        </button>
                    </td>
                `;
                queueTableBody.appendChild(tr);
            });

            // Attach checkbox event listeners
            document.querySelectorAll(".queue-item-cb").forEach(cb => {
                cb.addEventListener("change", updateQueueBatchButtonState);
            });
            updateQueueBatchButtonState();

        } catch (e) {
            console.error("Error loading queue:", e);
        }
    }

    function updateQueueBatchButtonState() {
        const checkedBoxes = document.querySelectorAll(".queue-item-cb:checked");
        if (btnBatchSeriesQueue) {
            btnBatchSeriesQueue.disabled = checkedBoxes.length === 0;
            btnBatchSeriesQueue.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/></svg>
                <span>📺 Ingest ${checkedBoxes.length > 0 ? checkedBoxes.length + ' ' : ''}Selected as Series</span>
            `;
        }
    }

    if (queueSelectAll) {
        queueSelectAll.addEventListener("change", () => {
            const isChecked = queueSelectAll.checked;
            document.querySelectorAll(".queue-item-cb:not(:disabled)").forEach(cb => {
                cb.checked = isChecked;
            });
            updateQueueBatchButtonState();
        });
    }

    if (btnBatchSeriesQueue) {
        btnBatchSeriesQueue.addEventListener("click", () => {
            const selectedIndices = Array.from(document.querySelectorAll(".queue-item-cb:checked"))
                .map(cb => parseInt(cb.getAttribute("data-idx")));
            const selectedFiles = selectedIndices.map(idx => incomingQueueFiles[idx]).filter(Boolean);
            if (selectedFiles.length === 0) return;

            // Switch to Upload Tab in Series Mode
            document.querySelector("[data-tab='upload-tab']").click();
            switchToSeriesBatchMode();
            addServerFilesToBatch(selectedFiles);
        });
    }

    window.queueIngestFile = (filePath, cleanedTitle) => {
        currentUploadedPath = filePath;
        document.querySelector("[data-tab='upload-tab']").click();
        switchToSingleMode();
        metaQuery.value = cleanedTitle;
        performImdbSearch(cleanedTitle);
    };

    // --- Tab 3: Collections Manager ---
    collectionSearch.addEventListener("input", filterCollections);
    btnSyncCollections.addEventListener("click", async () => {
        btnSyncCollections.disabled = true;
        btnSyncCollections.innerHTML = "<span>Syncing Collections...</span>";
        try {
            const resp = await apiFetch("/api/collections/sync", { method: "POST" });
            const res = await resp.json();
            if (res.success) {
                alert(`Synchronized ${res.updated_count} collections successfully!`);
                loadCollections();
            }
        } catch (e) {
            alert(`Collections sync error: ${e.message}`);
        } finally {
            btnSyncCollections.disabled = false;
            btnSyncCollections.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span>Sync All Collections</span>
            `;
        }
    });

    async function loadCollections() {
        collectionsGrid.innerHTML = "<div class='loading-state'>Loading collections from Jellyfin...</div>";
        try {
            const resp = await apiFetch("/api/collections");
            collectionsData = await resp.json();
            renderCollections(collectionsData);
        } catch (e) {
            collectionsGrid.innerHTML = `<div class='loading-state'>Failed to load collections: ${e.message}</div>`;
        }
    }

    function renderCollections(colls) {
        let totalOwned = 0;
        let totalMissing = 0;

        colls.forEach(c => {
            totalOwned += c.owned_count;
            totalMissing += c.missing_count;
        });

        totalCollectionsPill.textContent = `${colls.length} Collections`;
        totalOwnedPill.textContent = `${totalOwned} Owned`;
        totalMissingPill.textContent = `${totalMissing} Missing`;

        if (colls.length === 0) {
            collectionsGrid.innerHTML = "<div class='empty-state'>No collections found.</div>";
            return;
        }

        collectionsGrid.innerHTML = "";
        colls.forEach(c => {
            const card = document.createElement("div");
            card.className = "collection-card";
            
            let moviesHtml = "";
            (c.movies || []).forEach(m => {
                const cls = m.is_missing ? "missing" : "owned";
                const icon = m.is_missing ? "❌" : "✅";
                moviesHtml += `
                    <div class="movie-row ${cls}">
                        <span>${icon} ${m.name}</span>
                        <span>${m.year || ''}</span>
                    </div>
                `;
            });

            card.innerHTML = `
                <div class="collection-header">
                    <div class="collection-name">${c.name}</div>
                    <div class="collection-stats">
                        <span class="stat-tag stat-owned">${c.owned_count} owned</span>
                        ${c.missing_count > 0 ? `<span class="stat-tag stat-missing">${c.missing_count} missing</span>` : ''}
                    </div>
                </div>
                <div class="collection-movies-list">
                    ${moviesHtml}
                </div>
            `;
            collectionsGrid.appendChild(card);
        });
    }

    function filterCollections() {
        const query = collectionSearch.value.toLowerCase();
        const filtered = collectionsData.filter(c => c.name.toLowerCase().includes(query));
        renderCollections(filtered);
    }

    // --- Tab 4: Live Activity Console (SSE) ---
    let logEventSource = null;
    function connectSseLogs() {
        if (!isAuthenticated) return;
        if (logEventSource) {
            logEventSource.close();
            logEventSource = null;
        }
        logEventSource = new EventSource(apiUrl("/api/logs/stream"));
        logEventSource.onmessage = (event) => {
            const line = document.createElement("div");
            line.className = "terminal-line";
            line.textContent = event.data;
            terminalScreen.appendChild(line);
            terminalScreen.scrollTop = terminalScreen.scrollHeight;
        };
        logEventSource.onerror = () => {
            if (logEventSource) {
                logEventSource.close();
                logEventSource = null;
            }
            if (isAuthenticated) {
                setTimeout(connectSseLogs, 5000);
            }
        };
    }

    btnClearLogs.addEventListener("click", () => {
        terminalScreen.innerHTML = "<div class='terminal-line'>[System] Console cleared.</div>";
    });

    // --- Tab 5: Settings & Pathing Setup ---
    const cfgJellyfinUrl = document.getElementById("cfg-jellyfin-url");
    const cfgJellyfinUser = document.getElementById("cfg-jellyfin-user");
    const cfgJellyfinPass = document.getElementById("cfg-jellyfin-pass");
    const btnTestJellyfin = document.getElementById("btn-test-jellyfin");
    const jellyfinTestResult = document.getElementById("jellyfin-test-result");

    const inputMoviesDir = document.getElementById("input-movies-dir");
    const inputSeriesDir = document.getElementById("input-series-dir");
    const inputAdultDir = document.getElementById("input-adult-dir");
    const inputWatchDir = document.getElementById("input-watch-dir");
    const inputWatcherInterval = document.getElementById("input-watcher-interval");

    const badgeMoviesDir = document.getElementById("badge-movies-dir");
    const badgeSeriesDir = document.getElementById("badge-series-dir");
    const badgeAdultDir = document.getElementById("badge-adult-dir");
    const badgeWatchDir = document.getElementById("badge-watch-dir");

    const btnValidatePaths = document.getElementById("btn-validate-paths");
    const btnSaveSettings = document.getElementById("btn-save-settings");
    const btnResetDefaults = document.getElementById("btn-reset-defaults");
    const settingsAlertBox = document.getElementById("settings-alert-box");

    // Load full settings
    async function loadSettings() {
        try {
            const resp = await apiFetch("/api/settings");
            const s = await resp.json();

            cfgJellyfinUrl.value = s.JELLYFIN_URL || "";
            cfgJellyfinUser.value = s.JELLYFIN_USER || "";
            cfgJellyfinPass.value = s.JELLYFIN_PASS || "";

            inputMoviesDir.value = s.MOVIES_DIR || "";
            inputSeriesDir.value = s.SERIES_DIR || "";
            inputAdultDir.value = s.ADULT_DIR || "";
            inputWatchDir.value = s.WATCH_DIR || "";
            inputWatcherInterval.value = s.WATCHER_INTERVAL || 10;

            watcherToggle.checked = s.WATCHER_ENABLED !== false;
            watcherStatusText.textContent = watcherToggle.checked ? "Watcher Active" : "Watcher Disabled";

            validateAllPaths(false);
        } catch (e) {
            console.error("Error loading settings:", e);
        }
    }

    async function checkPath(path, badgeEl, autoCreate = false) {
        if (!path || path.trim() === "") {
            badgeEl.className = "path-badge";
            badgeEl.textContent = "Optional / Not Set";
            return;
        }

        badgeEl.className = "path-badge";
        badgeEl.textContent = "Checking...";

        try {
            const resp = await apiFetch("/api/settings/validate-path", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, create_if_missing: autoCreate })
            });
            const res = await resp.json();

            if (res.exists && res.is_dir) {
                badgeEl.className = "path-badge valid";
                badgeEl.textContent = `✔ Valid (${res.free_gb} GB Free)`;
            } else {
                badgeEl.className = "path-badge missing";
                badgeEl.textContent = "✖ Missing Directory";
            }
        } catch (e) {
            badgeEl.className = "path-badge missing";
            badgeEl.textContent = "✖ Check Failed";
        }
    }

    function validateAllPaths(autoCreate = false) {
        checkPath(inputMoviesDir.value, badgeMoviesDir, autoCreate);
        checkPath(inputSeriesDir.value, badgeSeriesDir, autoCreate);
        checkPath(inputAdultDir.value, badgeAdultDir, autoCreate);
        checkPath(inputWatchDir.value, badgeWatchDir, autoCreate);
    }

    // Real-time path change validation
    [inputMoviesDir, inputSeriesDir, inputAdultDir, inputWatchDir].forEach(input => {
        input.addEventListener("blur", () => validateAllPaths(false));
    });

    btnValidatePaths.addEventListener("click", () => {
        validateAllPaths(true);
        showAlert("Validated paths and created any missing directories on host.", "success");
    });

    // Test Jellyfin Connection
    btnTestJellyfin.addEventListener("click", async () => {
        btnTestJellyfin.disabled = true;
        jellyfinTestResult.className = "conn-status-tag";
        jellyfinTestResult.textContent = "Connecting...";

        try {
            const resp = await apiFetch("/api/settings/test-connection", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url: cfgJellyfinUrl.value,
                    user: cfgJellyfinUser.value,
                    pw: cfgJellyfinPass.value
                })
            });
            const res = await resp.json();

            if (res.success) {
                jellyfinTestResult.className = "conn-status-tag success";
                jellyfinTestResult.textContent = `✔ ${res.message}`;
            } else {
                jellyfinTestResult.className = "conn-status-tag error";
                jellyfinTestResult.textContent = `✖ ${res.error}`;
            }
        } catch (e) {
            jellyfinTestResult.className = "conn-status-tag error";
            jellyfinTestResult.textContent = `✖ Connection failed: ${e.message}`;
        } finally {
            btnTestJellyfin.disabled = false;
        }
    });

    // Save Settings
    btnSaveSettings.addEventListener("click", async () => {
        btnSaveSettings.disabled = true;
        btnSaveSettings.innerHTML = "<span>Saving...</span>";

        const payload = {
            JELLYFIN_URL: cfgJellyfinUrl.value,
            JELLYFIN_USER: cfgJellyfinUser.value,
            JELLYFIN_PASS: cfgJellyfinPass.value,
            MOVIES_DIR: inputMoviesDir.value,
            SERIES_DIR: inputSeriesDir.value,
            ADULT_DIR: inputAdultDir.value,
            WATCH_DIR: inputWatchDir.value,
            WATCHER_INTERVAL: parseInt(inputWatcherInterval.value) || 10,
            WATCHER_ENABLED: watcherToggle.checked
        };

        try {
            const resp = await apiFetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const res = await resp.json();

            if (res.success) {
                showAlert("Settings and paths updated and persisted successfully to data/settings.json!", "success");
                validateAllPaths(false);
                // Update header status
                checkServerStatus();
            } else {
                showAlert("Failed to save settings.", "error");
            }
        } catch (e) {
            showAlert(`Save error: ${e.message}`, "error");
        } finally {
            btnSaveSettings.disabled = false;
            btnSaveSettings.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                <span>Save Settings</span>
            `;
        }
    });

    // Reset Defaults
    btnResetDefaults.addEventListener("click", () => {
        if (confirm("Reset paths and settings to standard server defaults?")) {
            cfgJellyfinUrl.value = "http://localhost:8096";
            cfgJellyfinUser.value = "";
            cfgJellyfinPass.value = "";
            inputMoviesDir.value = "/media/movies";
            inputSeriesDir.value = "/media/tv";
            inputAdultDir.value = "/media/adult";
            inputWatchDir.value = "/downloads";
            inputWatcherInterval.value = 10;
            validateAllPaths(false);
            showAlert("Values reset to default. Click 'Save Settings' to apply.", "success");
        }
    });

    function showAlert(msg, type) {
        settingsAlertBox.className = `alert-box ${type}`;
        settingsAlertBox.textContent = msg;
        settingsAlertBox.classList.remove("hidden");
        setTimeout(() => {
            settingsAlertBox.classList.add("hidden");
        }, 6000);
    }

    watcherToggle.addEventListener("change", async () => {
        const enabled = watcherToggle.checked;
        watcherStatusText.textContent = enabled ? "Watcher Active" : "Watcher Disabled";
        try {
            await apiFetch("/api/watcher/toggle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled })
            });
        } catch (e) {
            console.error("Watcher toggle error:", e);
        }
    });

    btnForceJellyfinRefresh.addEventListener("click", async () => {
        btnForceJellyfinRefresh.disabled = true;
        try {
            const resp = await apiFetch("/api/refresh-library", { method: "POST" });
            const res = await resp.json();
            if (res.success) alert("Jellyfin library rescan triggered!");
        } catch (e) {
            alert("Error triggering refresh: " + e.message);
        } finally {
            btnForceJellyfinRefresh.disabled = false;
        }
    });

    // Server Status Check
    function checkServerStatus() {
        const host = window.location.hostname;
        const port = window.location.port ? `:${window.location.port}` : "";
        const curAccessEl = document.getElementById("current-access-url");
        if (curAccessEl) {
            curAccessEl.textContent = `${window.location.protocol}//${host}${port}${window.location.pathname}`;
        }
        const tailHintEl = document.getElementById("tailscale-status-hint");
        if (tailHintEl) {
            if (host.startsWith("100.")) {
                tailHintEl.textContent = `Active Tailscale session (${host})`;
            } else {
                tailHintEl.textContent = "Not required (Connected via standard LAN / Localhost)";
            }
        }

        apiFetch("/api/status")
            .then(r => r.json())
            .then(st => {
                const dot = document.getElementById("server-status-dot");
                const text = document.getElementById("server-status-text");
                if (st.jellyfin_online) {
                    dot.className = "status-indicator online";
                    text.textContent = "CONNECTED (" + st.jellyfin_url.replace("http://", "").split("/")[0] + ")";
                } else {
                    dot.className = "status-indicator busy";
                    text.textContent = "DISCONNECTED / CHECK SETTINGS";
                }
                const watchPathEl = document.getElementById("watch-folder-path");
                if (watchPathEl) watchPathEl.textContent = st.watch_dir;
            })
            .catch(console.error);
    }

    // Initial load with auth gate
    checkAuth().then(authed => {
        if (authed) {
            checkServerStatus();
            loadSettings();
            loadMediaDirectories();
            loadIncomingQueue();
            connectSseLogs();
        }
    });
});
