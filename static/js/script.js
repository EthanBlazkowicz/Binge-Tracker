function setBg(bgStyle) { document.body.style.background = bgStyle; localStorage.setItem('bingeBg', bgStyle); }
        window.onload = () => { 
            const savedBg = localStorage.getItem('bingeBg'); 
            if (savedBg) document.body.style.background = savedBg; 

            const tooltip = document.getElementById('global-tooltip');
            document.querySelectorAll('.ep-box').forEach(box => {
                box.addEventListener('mouseenter', (e) => {
                    const rect = box.getBoundingClientRect();
                    tooltip.textContent = box.getAttribute('data-tooltip');
                    tooltip.style.left = (rect.left + rect.width / 2) + 'px';
                    tooltip.style.top = (rect.top - 10) + 'px';
                    tooltip.classList.add('show');
                });
                box.addEventListener('mouseleave', () => {
                    tooltip.classList.remove('show');
                });
            });

            // Mobile long-press support for setting end episode
            let longPressTimer = null;
            let longPressTarget = null;
            document.querySelectorAll('.ep-box').forEach(box => {
                box.addEventListener('touchstart', (e) => {
                    longPressTarget = box;
                    longPressTimer = setTimeout(() => {
                        e.preventDefault();
                        const epId = box.getAttribute('onclick').match(/toggleEp[(](\\d+)/)[1];
                        setEndEp(e, parseInt(epId));
                        longPressTarget = null;
                    }, 500);
                }, { passive: false });
                box.addEventListener('touchend', () => {
                    clearTimeout(longPressTimer);
                    longPressTarget = null;
                });
                box.addEventListener('touchmove', () => {
                    clearTimeout(longPressTimer);
                    longPressTarget = null;
                });
            });
        }
        function toggleMenu() { const menu = document.getElementById('bgMenu'); menu.style.display = (menu.style.display === 'flex') ? 'none' : 'flex'; }

        function toggleEp(epId, element) {
            fetch('/toggle/' + epId, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    if(data.watched) element.classList.add('watched');
                    else element.classList.remove('watched');
                    updateStats(data.target_id, data.stats);
                }
            });
        }
        function setEndEp(event, epId) {
            event.preventDefault();
            fetch('/set_end/' + epId, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    updateEndEpisode(data.target_id, data.ep_id, data.show_title, data.stats);
                }
            });
        }
        function deleteTarget(targetId) {
            if(confirm("Delete this Binge Target?")) {
                fetch('/delete/' + targetId, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if(data.success) {
                        const elem = document.getElementById('card-' + targetId);
                        elem.style.transform = "scale(0.95)"; elem.style.opacity = 0;
                        setTimeout(() => elem.remove(), 400);
                    }
                });
            }
        }
        function refreshTarget(targetId) {
            const btn = document.querySelector('#card-' + targetId + ' .action-group .btn:first-child');
            if(!btn) return;
            const originalText = btn.innerHTML;
            btn.innerHTML = '...';
            btn.disabled = true;
            fetch('/refresh/' + targetId, { method: 'POST' })
            .then(res => res.json())
            .then(data => { 
                if(data.success) {
                    window.location.reload();
                } else {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                    alert('Refresh failed');
                }
            })
            .catch(err => {
                console.error(err);
                btn.innerHTML = originalText;
                btn.disabled = false;
                alert('Error refreshing');
            });
        }
        function moveTarget(targetId, direction) {
            const currentCard = document.getElementById('card-' + targetId);
            if (!currentCard) return;
            
            const sibling = direction === 'up' ? currentCard.previousElementSibling : currentCard.nextElementSibling;
            
            if (sibling && sibling.classList.contains('target-card')) {
                const currentRect = currentCard.getBoundingClientRect();
                const siblingRect = sibling.getBoundingClientRect();
                const dy = siblingRect.top - currentRect.top;

                currentCard.style.transition = 'transform 0.4s ease-in-out, box-shadow 0.4s ease-in-out';
                currentCard.style.zIndex = '100';
                currentCard.style.position = 'relative';
                
                sibling.style.transition = 'transform 0.4s ease-in-out';
                sibling.style.position = 'relative';

                requestAnimationFrame(() => {
                    currentCard.style.transform = `translateY(${dy}px) scale(1.02)`;
                    currentCard.style.boxShadow = '0 25px 50px rgba(0,0,0,0.6)';
                    sibling.style.transform = `translateY(${-dy}px)`;
                });

                setTimeout(() => {
                    // Reset styles
                    currentCard.style.transition = '';
                    currentCard.style.transform = '';
                    currentCard.style.boxShadow = '';
                    currentCard.style.zIndex = '';
                    currentCard.style.position = '';
                    
                    sibling.style.transition = '';
                    sibling.style.transform = '';
                    sibling.style.position = '';

                    // Swap in DOM
                    if (direction === 'up') {
                        sibling.parentNode.insertBefore(currentCard, sibling);
                    } else {
                        sibling.parentNode.insertBefore(sibling, currentCard);
                    }

                    // Update backend silently
                    fetch('/move/' + targetId + '/' + direction, { method: 'POST' });
                }, 400);
            } else {
                fetch('/move/' + targetId + '/' + direction, { method: 'POST' })
                .then(res => res.json())
                .then(data => { if(data.success) window.location.reload(); });
            }
        }
        function updateStats(targetId, stats) {
            const bar = document.getElementById('bar-' + targetId);
            const overlay = document.getElementById('overlay-' + targetId);
            const txt = document.getElementById('stats-' + targetId);
            const daily = document.getElementById('daily-' + targetId);
            if(bar) bar.style.width = stats.progress_percent + '%';
            if(overlay) overlay.innerText = stats.progress_percent + '%';
            if(txt) txt.innerText = stats.text;
            if(daily) {
                if (stats.daily_mins != null) daily.innerHTML = '<span class="num">' + stats.daily_mins + '</span><span class="label">min/day</span>';
                else daily.innerHTML = '<span class="label">No Goal</span>';
            }
        }
        function updateEndEpisode(targetId, newEndEpId, showTitle, stats) {
            const card = document.getElementById('card-' + targetId);
            if(!card) return;

            // Find the show section by matching the show title
            const newEndBox = card.querySelector('.ep-box[onclick*="' + newEndEpId + '"]');
            if(!newEndBox) return;

            // Get the show section containing this episode
            const showSection = newEndBox.closest('.show-section');
            if(showSection) {
                // Remove end-ep class from all episodes in this show
                showSection.querySelectorAll('.ep-box.end-ep').forEach(box => box.classList.remove('end-ep'));
            }

            // Add end-ep class to new end episode
            newEndBox.classList.add('end-ep');

            // Update dimmed state only for episodes after the end point within the same show
            if(showSection) {
                // Get all ep-boxes in this show section in order
                const allEpsInShow = Array.from(showSection.querySelectorAll('.ep-box'));
                const endIndex = allEpsInShow.indexOf(newEndBox);
                allEpsInShow.forEach((box, idx) => {
                    if(idx > endIndex) {
                        box.classList.add('dimmed');
                    } else {
                        box.classList.remove('dimmed');
                    }
                });
            }

            // Update stats
            updateStats(targetId, stats);
        }
