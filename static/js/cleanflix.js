(function() {
    'use strict';

    console.log('[Cleanflix] Monochrome Modern Square Theme Engine & HUD v5 Activated');

    let introPlaying = false;
    let sidebarLoaded = false;

    /* =========================================================================
       0. Web Audio UI Sound Effects (SFX) Synthesizer Engine
       ========================================================================= */
    let sfxEnabled = localStorage.getItem('cleanflix_sfx_enabled') !== 'false';
    let audioCtx = null;

    function getAudioContext() {
        if (!audioCtx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                audioCtx = new AudioContext();
            }
        }
        if (audioCtx && audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
        return audioCtx;
    }

    // Auto-unlock Web Audio on first user interaction gesture
    function unlockAudio() {
        getAudioContext();
        window.removeEventListener('pointerdown', unlockAudio);
        window.removeEventListener('keydown', unlockAudio);
        window.removeEventListener('click', unlockAudio);
    }
    window.addEventListener('pointerdown', unlockAudio, { passive: true });
    window.addEventListener('keydown', unlockAudio, { passive: true });
    window.addEventListener('click', unlockAudio, { passive: true });

    function playSfx(type) {
        if (!sfxEnabled) return;
        try {
            const ctx = getAudioContext();
            if (!ctx || ctx.state !== 'running') return;
            const now = ctx.currentTime;

            if (type === 'hover') {
                // Subtle tactile micro-tick (15ms)
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                const baseFreq = 2100 + (Math.random() * 160 - 80);
                osc.frequency.setValueAtTime(baseFreq, now);
                osc.frequency.exponentialRampToValueAtTime(750, now + 0.014);
                gain.gain.setValueAtTime(0.028, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.015);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + 0.016);
            } else if (type === 'click') {
                // Crisp punchy tactile mechanical click (28ms)
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(520, now);
                osc.frequency.exponentialRampToValueAtTime(110, now + 0.026);
                gain.gain.setValueAtTime(0.065, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.028);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + 0.03);
            } else if (type === 'whoosh') {
                // Futuristic subtle sweep for drawer / sidebar HUD
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(320, now);
                osc.frequency.exponentialRampToValueAtTime(640, now + 0.07);
                gain.gain.setValueAtTime(0.04, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.07);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + 0.075);
            } else if (type === 'chime') {
                // Harmonic 3-note confirmation chime
                [523.25, 659.25, 783.99].forEach((freq, idx) => {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(freq, now + idx * 0.045);
                    gain.gain.setValueAtTime(0.04, now + idx * 0.045);
                    gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.045 + 0.16);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(now + idx * 0.045);
                    osc.stop(now + idx * 0.045 + 0.17);
                });
            }
        } catch (e) {
            // Audio error silent fallback
        }
    }

    // Global Event Delegation for SFX (Zero-overhead, 144Hz responsive)
    let lastHoverTime = 0;
    document.addEventListener('mouseover', function(e) {
        const target = e.target.closest(
            '.card, .cardBox, .emby-button, .button-submit, .headerButton, .navMenuOption, .cf-genre-chip, .cf-folder-header, .cf-sidebar-toggle-btn, .cleanflix-header-brand, #cleanflix-sfx-btn, .paper-icon-button-light, .actionSheetMenuItem, .listItem'
        );
        if (target) {
            const now = Date.now();
            if (now - lastHoverTime > 36) {
                lastHoverTime = now;
                playSfx('hover');
            }
        }
    }, { passive: true });

    document.addEventListener('click', function(e) {
        const target = e.target.closest(
            '.card, .cardBox, .cardOverlayFab-primary, .cardOverlayButtonIcon, .emby-button, .button-submit, .headerButton, .navMenuOption, .cf-genre-chip, .cf-folder-header, .cf-sidebar-toggle-btn, .cleanflix-header-brand, #cleanflix-sfx-btn, .paper-icon-button-light, .actionSheetMenuItem, .emby-checkbox, .checkboxOutline, a[is="emby-linkbutton"]'
        );
        if (target) {
            playSfx('click');
        }
    }, { passive: true });

    /* =========================================================================
       1. Folder & Genre Icons
       ========================================================================= */
    const GENRE_ICONS = {
        'Action': '💥',
        'Action & Adventure': '⚔️',
        'Adventure': '🧭',
        'Animation': '🎨',
        'Comedy': '😂',
        'Crime': '🕵️',
        'Documentary': '📽️',
        'Drama': '🎭',
        'Family': '👨‍👩‍👧',
        'Fantasy': '🧙',
        'History': '📜',
        'Horror': '👻',
        'Music': '🎵',
        'Mystery': '🔍',
        'Romance': '💖',
        'Science Fiction': '🚀',
        'Sci-Fi': '🚀',
        'Sci-Fi & Fantasy': '🌌',
        'Thriller': '⚡',
        'TV Movie': '📺',
        'War': '🛡️',
        'War & Politics': '🏛️',
        'Western': '🤠',
        'Kids': '🧸',
        'Short': '⏱️',
        'Sport': '⚽',
        'Sports': '⚽',
        'Reality': '📹',
        'News': '📰',
        'Talk': '🎙️',
        'Indie': '🎸'
    };

    const FOLDER_ICONS = {
        'movies': '🎬',
        'tvshows': '📺',
        'boxsets': '🗂️',
        'anime': '🎌',
        'children': '👶',
        'music': '🎧'
    };

    function getFolderIcon(type, name) {
        const lowerName = (name || '').toLowerCase();
        if (lowerName.includes('anime')) return '🎌';
        if (lowerName.includes('child') || lowerName.includes('kid')) return '👶';
        if (lowerName.includes('eesti') || lowerName.includes('eston')) return '🇪🇪';
        if (type && FOLDER_ICONS[type.toLowerCase()]) return FOLDER_ICONS[type.toLowerCase()];
        if (lowerName.includes('movie')) return '🎬';
        if (lowerName.includes('show') || lowerName.includes('series') || lowerName.includes('tv')) return '📺';
        if (lowerName.includes('collection')) return '🗂️';
        return '📁';
    }

    function getGenreIcon(name) {
        if (!name) return '🏷️';
        if (GENRE_ICONS[name]) return GENRE_ICONS[name];
        for (const [key, icon] of Object.entries(GENRE_ICONS)) {
            if (name.toLowerCase().includes(key.toLowerCase())) {
                return icon;
            }
        }
        return '🏷️';
    }

    /* =========================================================================
       2. Login & Branding Handlers
       ========================================================================= */

    function bindLoginTriggers() {
        const loginPage = document.getElementById('loginPage');
        if (!loginPage) return;

        const userCards = loginPage.querySelectorAll('#divUsers .card');
        userCards.forEach(function(card) {
            if (!card.dataset.cfBound) {
                card.dataset.cfBound = 'true';
                card.addEventListener('click', function() {
                    sessionStorage.setItem('cleanflix_trigger_intro', 'true');
                });
            }
        });

        const form = loginPage.querySelector('form.manualLoginForm');
        if (form && !form.dataset.cfBound) {
            form.dataset.cfBound = 'true';
            form.addEventListener('submit', function() {
                sessionStorage.setItem('cleanflix_trigger_intro', 'true');
            });
        }

        const submitBtns = loginPage.querySelectorAll('.button-submit, .btnManual');
        submitBtns.forEach(function(btn) {
            if (!btn.dataset.cfBound) {
                btn.dataset.cfBound = 'true';
                btn.addEventListener('click', function() {
                    sessionStorage.setItem('cleanflix_trigger_intro', 'true');
                });
            }
        });
    }

    function injectCleanflixBrand() {
        const loginPage = document.getElementById('loginPage');
        if (!loginPage || loginPage.classList.contains('hide')) return;

        bindLoginTriggers();

        const card = loginPage.querySelector('.padded-bottom-page');
        if (!card) return;

        if (!document.getElementById('cleanflix-brand-header')) {
            const brandHeader = document.createElement('div');
            brandHeader.id = 'cleanflix-brand-header';
            brandHeader.innerHTML = `
                <div class="cleanflix-title-container">
                    <span class="cf-word-clean">CLEAN</span><span class="cf-word-flix">FLIX</span>
                </div>
                <div class="cf-subtitle">MEDIA SERVER</div>
            `;
            card.insertBefore(brandHeader, card.firstChild);
        }
    }

    function injectHeaderBrand() {
        const skinHeader = document.querySelector('.skinHeader');
        if (!skinHeader) return;

        // 1. Inject Monochrome Brand Wordmark
        if (!document.querySelector('.cleanflix-header-brand')) {
            const headerLeft = skinHeader.querySelector('.headerLeft') || skinHeader.querySelector('.headerTop');
            if (headerLeft) {
                const brandSpan = document.createElement('span');
                brandSpan.className = 'cleanflix-header-brand';
                brandSpan.innerHTML = '<span class="cf-clean">CLEAN</span><span class="cf-flix">FLIX</span>';
                brandSpan.title = 'Cleanflix Media Server';
                brandSpan.onclick = function() {
                    if (window.appRouter && typeof window.appRouter.goHome === 'function') {
                        window.appRouter.goHome();
                    } else {
                        window.location.hash = '#/home.html';
                    }
                };
                headerLeft.appendChild(brandSpan);
            }
        }

        // 2. Inject SFX Audio Toggle Button into Top Header
        if (!document.getElementById('cleanflix-sfx-btn')) {
            const headerRight = skinHeader.querySelector('.headerRight') || skinHeader.querySelector('.headerTop');
            if (headerRight) {
                const sfxBtn = document.createElement('button');
                sfxBtn.id = 'cleanflix-sfx-btn';
                sfxBtn.type = 'button';
                sfxBtn.className = 'headerButton cleanflix-sfx-btn';
                sfxBtn.title = sfxEnabled ? 'UI Sound Effects: ON (Click to Mute)' : 'UI Sound Effects: OFF (Click to Enable)';
                sfxBtn.innerHTML = `
                    <span class="material-icons cleanflix-sfx-icon" style="font-size:1.3rem;vertical-align:middle;">
                        ${sfxEnabled ? 'volume_up' : 'volume_off'}
                    </span>
                `;

                sfxBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    sfxEnabled = !sfxEnabled;
                    localStorage.setItem('cleanflix_sfx_enabled', sfxEnabled ? 'true' : 'false');
                    sfxBtn.title = sfxEnabled ? 'UI Sound Effects: ON (Click to Mute)' : 'UI Sound Effects: OFF (Click to Enable)';
                    const icon = sfxBtn.querySelector('.cleanflix-sfx-icon');
                    if (icon) {
                        icon.textContent = sfxEnabled ? 'volume_up' : 'volume_off';
                    }
                    if (sfxEnabled) {
                        playSfx('chime');
                    }
                });

                headerRight.insertBefore(sfxBtn, headerRight.firstChild);
            }
        }
    }

    function playPostLoginSplash() {
        if (introPlaying) return;
        introPlaying = true;

        console.log('[Cleanflix] Playing post-login cinematic intro...');

        const oldOverlay = document.getElementById('cleanflix-splash-overlay');
        if (oldOverlay) oldOverlay.remove();

        const overlay = document.createElement('div');
        overlay.id = 'cleanflix-splash-overlay';
        overlay.innerHTML = `
            <div id="cleanflix-splash-brand">
                <span class="cf-clean">CLEAN</span><span class="cf-flix">FLIX</span>
            </div>
            <video id="cleanflix-splash-video" playsinline preload="auto" src="custom-assets/splash.mp4"></video>
            <button id="cleanflix-skip-btn" type="button">
                <span>Skip</span>
                <span class="material-icons" style="font-size:1.1rem;margin-left:4px;vertical-align:middle;">arrow_forward</span>
            </button>
        `;

        document.body.appendChild(overlay);

        const video = overlay.querySelector('video');
        const skipBtn = overlay.querySelector('#cleanflix-skip-btn');

        function finishIntro() {
            if (!overlay || overlay.dataset.finished) return;
            overlay.dataset.finished = 'true';
            overlay.style.opacity = '0';
            setTimeout(function() {
                if (video) {
                    video.pause();
                    video.src = '';
                }
                overlay.remove();
                introPlaying = false;
            }, 650);
        }

        skipBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            finishIntro();
        });

        video.addEventListener('ended', finishIntro);
        video.addEventListener('error', function(err) {
            console.error('[Cleanflix] Video playback note:', err);
            finishIntro();
        });

        video.muted = false;
        const playPromise = video.play();
        if (playPromise !== undefined) {
            playPromise.catch(function(err) {
                console.log('[Cleanflix] Audio autoplay fallback to muted:', err);
                video.muted = true;
                video.play().catch(function() {
                    finishIntro();
                });
            });
        }
    }

    /* =========================================================================
       3. Home HUD Genre Side Panel (Monochrome Edition)
       ========================================================================= */

    function createGenreSidebarDOM() {
        let sidebar = document.getElementById('cleanflix-genre-sidebar');
        if (sidebar) return sidebar;

        sidebar = document.createElement('aside');
        sidebar.id = 'cleanflix-genre-sidebar';
        sidebar.className = 'cleanflix-genre-sidebar';

        if (localStorage.getItem('cleanflix_sidebar_collapsed') === 'true') {
            sidebar.classList.add('collapsed');
            document.body.classList.add('cleanflix-sidebar-collapsed');
        }

        sidebar.innerHTML = `
            <div class="cf-sidebar-header">
                <div class="cf-sidebar-title">
                    <span class="cf-sidebar-title-icon">🏷️</span>
                    <span class="cf-sidebar-title-text">GENRES HUD</span>
                </div>
                <button id="cf-sidebar-toggle-btn" class="cf-sidebar-toggle-btn" type="button" title="Collapse / Expand Sidebar">
                    <span class="material-icons cf-chevron" style="font-size:1.3rem;">chevron_left</span>
                </button>
            </div>
            <div class="cf-sidebar-search">
                <input type="text" id="cf-genre-filter-input" placeholder="Filter genres..." spellcheck="false" autocomplete="off" />
            </div>
            <div class="cf-sidebar-scrollable" id="cf-sidebar-scrollable">
                <div class="cf-sidebar-loading" style="padding:1.5rem 1rem;text-align:center;color:#ffffff;font-size:0.85rem;">
                    Loading genres...
                </div>
            </div>
        `;

        document.body.appendChild(sidebar);

        const toggleBtn = sidebar.querySelector('#cf-sidebar-toggle-btn');
        const chevron = sidebar.querySelector('.cf-chevron');
        toggleBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            playSfx('whoosh');
            const isCollapsed = sidebar.classList.toggle('collapsed');
            if (isCollapsed) {
                document.body.classList.add('cleanflix-sidebar-collapsed');
                localStorage.setItem('cleanflix_sidebar_collapsed', 'true');
                if (chevron) chevron.textContent = 'chevron_right';
            } else {
                document.body.classList.remove('cleanflix-sidebar-collapsed');
                localStorage.setItem('cleanflix_sidebar_collapsed', 'false');
                if (chevron) chevron.textContent = 'chevron_left';
            }
        });

        if (sidebar.classList.contains('collapsed') && chevron) {
            chevron.textContent = 'chevron_right';
        }

        const filterInput = sidebar.querySelector('#cf-genre-filter-input');
        filterInput.addEventListener('input', function(e) {
            const query = (e.target.value || '').trim().toLowerCase();
            const chips = sidebar.querySelectorAll('.cf-genre-chip');
            chips.forEach(function(chip) {
                const name = (chip.dataset.genreName || '').toLowerCase();
                if (!query || name.includes(query)) {
                    chip.style.display = 'flex';
                } else {
                    chip.style.display = 'none';
                }
            });

            const groups = sidebar.querySelectorAll('.cf-folder-group');
            groups.forEach(function(group) {
                if (!query) {
                    group.style.display = 'block';
                    return;
                }
                const visibleChips = group.querySelectorAll('.cf-genre-chip:not([style*="display: none"])');
                group.style.display = visibleChips.length > 0 ? 'block' : 'none';
            });
        });

        return sidebar;
    }

    function renderGenreSidebar(folders) {
        const sidebar = createGenreSidebarDOM();
        const container = sidebar.querySelector('#cf-sidebar-scrollable');
        if (!container) return;

        let html = '';
        folders.forEach(function(folder) {
            if (!folder.genres || folder.genres.length === 0) return;

            const fIcon = getFolderIcon(folder.type, folder.name);
            html += `
                <div class="cf-folder-group" data-folder-id="${folder.id}">
                    <div class="cf-folder-header" data-folder-id="${folder.id}" title="Browse all in ${folder.name}">
                        <span class="cf-folder-icon">${fIcon}</span>
                        <span class="cf-folder-name">${folder.name}</span>
                        <span class="cf-folder-count">${folder.genres.length}</span>
                    </div>
                    <div class="cf-genre-grid">
            `;

            folder.genres.forEach(function(genre) {
                const gIcon = getGenreIcon(genre.name);
                html += `
                    <a class="cf-genre-chip" href="#/list?genreId=${genre.id}&parentId=${folder.id}" data-genre-id="${genre.id}" data-folder-id="${folder.id}" data-genre-name="${genre.name}" title="${genre.name} (${folder.name})">
                        <span class="cf-genre-emoji">${gIcon}</span>
                        <span class="cf-genre-name">${genre.name}</span>
                    </a>
                `;
            });

            html += `
                    </div>
                </div>
            `;
        });

        if (!html) {
            container.innerHTML = '<div style="padding:1.5rem;text-align:center;color:#888888;font-size:0.8rem;">No genres available.</div>';
            return;
        }

        container.innerHTML = html;

        container.querySelectorAll('.cf-folder-header').forEach(function(header) {
            header.addEventListener('click', function(e) {
                e.preventDefault();
                const folderId = header.dataset.folderId;
                const folderObj = folders.find(f => f.id === folderId);
                const serverId = window.ApiClient ? window.ApiClient.serverId() : '';
                if (window.appRouter && typeof window.appRouter.showItem === 'function' && folderObj) {
                    window.appRouter.showItem({ Id: folderId, Type: 'CollectionFolder', CollectionType: folderObj.type, ServerId: serverId });
                } else {
                    window.location.hash = '#/movies?topParentId=' + folderId;
                }
            });
        });

        container.querySelectorAll('.cf-genre-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.preventDefault();
                const genreId = chip.dataset.genreId;
                const folderId = chip.dataset.folderId;
                const serverId = window.ApiClient ? window.ApiClient.serverId() : '';
                const targetUrl = '#/list?genreId=' + genreId + '&serverId=' + serverId + '&parentId=' + folderId;

                if (window.appRouter && typeof window.appRouter.show === 'function') {
                    window.appRouter.show(targetUrl);
                } else {
                    window.location.hash = targetUrl;
                }
            });
        });
    }

    async function loadGenreSidebarData() {
        if (!window.ApiClient) return;
        const userId = window.ApiClient.getCurrentUserId();
        if (!userId) {
            setTimeout(function() {
                if (window.ApiClient && window.ApiClient.getCurrentUserId() && !sidebarLoaded) {
                    loadGenreSidebarData();
                }
            }, 600);
            return;
        }

        const cacheKey = 'cleanflix_genres_cache_' + userId;
        const cached = sessionStorage.getItem(cacheKey);
        if (cached) {
            try {
                const parsed = JSON.parse(cached);
                if (Array.isArray(parsed) && parsed.length > 0) {
                    sidebarLoaded = true;
                    renderGenreSidebar(parsed);
                    return;
                }
            } catch (err) {
                console.warn('[Cleanflix] Cache parse error:', err);
            }
        }

        try {
            console.log('[Cleanflix] Fetching library views and genres for user HUD...');
            const viewsResponse = await window.ApiClient.getUserViews();
            const views = viewsResponse.Items || [];

            const folderPromises = views.map(async function(view) {
                try {
                    const genreResp = await window.ApiClient.getGenres(userId, {
                        parentId: view.Id,
                        SortBy: 'SortName',
                        SortOrder: 'Ascending'
                    });
                    const genres = (genreResp.Items || []).map(g => ({
                        id: g.Id,
                        name: g.Name
                    }));
                    return {
                        id: view.Id,
                        name: view.Name,
                        type: view.CollectionType || '',
                        genres: genres
                    };
                } catch (err) {
                    console.error('[Cleanflix] Error fetching genres for ' + view.Name, err);
                    return { id: view.Id, name: view.Name, type: view.CollectionType || '', genres: [] };
                }
            });

            const folderResults = await Promise.all(folderPromises);
            sessionStorage.setItem(cacheKey, JSON.stringify(folderResults));
            sidebarLoaded = true;
            renderGenreSidebar(folderResults);
        } catch (err) {
            console.error('[Cleanflix] Error building genre sidebar:', err);
        }
    }

    function updateSidebarVisibility() {
        const hash = window.location.hash || '';
        const indexPage = document.getElementById('indexPage');
        const loginPage = document.getElementById('loginPage');
        const isLogin = hash.includes('login') || (loginPage && !loginPage.classList.contains('hide') && !hash.includes('home'));
        const isPlaying = document.querySelector('.videoPlayerContainer:not(.hide)');

        // We want the sidebar visible on Home HUD
        const isHome = !isLogin && !isPlaying && (
            hash === '' ||
            hash === '#' ||
            hash === '#/' ||
            hash.includes('home') ||
            (indexPage && !indexPage.classList.contains('hide') && !hash.includes('item') && !hash.includes('details') && !hash.includes('settings') && !hash.includes('dashboard') && !hash.includes('list') && !hash.includes('movies') && !hash.includes('tv'))
        );

        let sidebar = document.getElementById('cleanflix-genre-sidebar');

        if (isHome) {
            if (!sidebar) {
                sidebar = createGenreSidebarDOM();
            }
            sidebar.style.display = 'flex';
            document.body.classList.add('cleanflix-has-sidebar');

            if (!sidebarLoaded) {
                loadGenreSidebarData();
            }
        } else {
            if (sidebar) {
                sidebar.style.display = 'none';
            }
            document.body.classList.remove('cleanflix-has-sidebar');
        }
    }

    /* =========================================================================
       4. Main Lifecycle & Route Observer
       ========================================================================= */

    function onRouteOrViewChange() {
        const hash = window.location.hash || '';
        const loginPage = document.getElementById('loginPage');
        const isLogin = hash.includes('login') || (loginPage && !loginPage.classList.contains('hide') && !hash.includes('home'));

        if (isLogin) {
            sessionStorage.removeItem('cleanflix_intro_completed');
            injectCleanflixBrand();
            const sidebar = document.getElementById('cleanflix-genre-sidebar');
            if (sidebar) sidebar.style.display = 'none';
            document.body.classList.remove('cleanflix-has-sidebar');
        } else {
            const shouldTrigger = sessionStorage.getItem('cleanflix_trigger_intro') === 'true';
            const alreadyCompleted = sessionStorage.getItem('cleanflix_intro_completed') === 'true';

            if (shouldTrigger && !alreadyCompleted) {
                sessionStorage.removeItem('cleanflix_trigger_intro');
                sessionStorage.setItem('cleanflix_intro_completed', 'true');
                playPostLoginSplash();
            }

            injectHeaderBrand();
            updateSidebarVisibility();
        }
    }

    // Event-driven lifecycle triggers
    window.addEventListener('hashchange', onRouteOrViewChange);
    window.addEventListener('popstate', onRouteOrViewChange);
    document.addEventListener('viewshow', onRouteOrViewChange);
    document.addEventListener('DOMContentLoaded', onRouteOrViewChange);

    // Debounced observer for SPA view injections
    let checkTimeout = null;
    function scheduleCheck() {
        if (checkTimeout) return;
        checkTimeout = setTimeout(function() {
            checkTimeout = null;
            onRouteOrViewChange();
        }, 150);
    }

    const pageObserver = new MutationObserver(function(mutations) {
        for (let i = 0; i < mutations.length; i++) {
            if (mutations[i].addedNodes.length > 0) {
                scheduleCheck();
                break;
            }
        }
    });

    if (document.body) {
        pageObserver.observe(document.body, { childList: true, subtree: true });
    }

    scheduleCheck();
})();
