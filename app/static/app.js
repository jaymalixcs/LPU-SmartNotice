// LPU SmartNotice Frontend Application Logic

let activeStudentId = "STU-101";
let demoStudents = [];
let currentPage = 1;

document.addEventListener("DOMContentLoaded", () => {
    loadStudents();
    loadHealthDashboard();
    loadUmsStatus();
    updateSyncSnippetDisplay();
});

function switchTab(tabId, evt) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

    document.getElementById(tabId).classList.add("active");
    if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");

    if (tabId === "feedTab") loadPersonalizedFeed();
    if (tabId === "timetableTab") loadAffectedClasses();
    if (tabId === "healthTab") loadHealthDashboard();
}

async function loadStudents() {
    try {
        const res = await fetch("/api/v1/students");
        if (!res.ok) throw new Error("Failed to load students");
        demoStudents = await res.json();

        const select = document.getElementById("studentSelector");
        select.innerHTML = "";
        demoStudents.forEach(stu => {
            const opt = document.createElement("option");
            opt.value = stu.student_id;
            opt.textContent = `${stu.name} (${stu.program})`;
            select.appendChild(opt);
        });

        if (demoStudents.length > 0) {
            if (!activeStudentId || !demoStudents.some(s => s.student_id === activeStudentId)) {
                activeStudentId = demoStudents[0].student_id;
            }
            select.value = activeStudentId;
            updateStudentCard();
            loadPersonalizedFeed();
        }
    } catch (e) {
        console.error("Error loading student profiles:", e);
    }
}

function onStudentChange() {
    activeStudentId = document.getElementById("studentSelector").value;
    updateStudentCard();
    loadPersonalizedFeed();
}

function updateStudentCard() {
    const student = demoStudents.find(s => s.student_id === activeStudentId);
    if (student) {
        document.getElementById("studentDetails").innerHTML = `
            <strong>Year ${student.year} | Sem ${student.semester}</strong><br>
            Department: ${student.department}<br>
            Interests: ${student.interests.join(", ")}
        `;
    }
}

let currentFeedApplicability = "ALL";

function setFeedApplicability(tier, evt) {
    currentFeedApplicability = tier;
    document.querySelectorAll("#feedTierFilters .pill-btn").forEach(btn => btn.classList.remove("active"));
    if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");
    loadPersonalizedFeed(1);
}

async function loadPersonalizedFeed(page = 1) {
    currentPage = page;
    const feedContainer = document.getElementById("feedList");
    feedContainer.innerHTML = `<div class="loading-spinner">Loading personalized feed for ${activeStudentId}...</div>`;

    const cat = document.getElementById("feedCategoryFilter") ? document.getElementById("feedCategoryFilter").value : "";
    let url = `/api/v1/feed/${activeStudentId}/feed?page=${page}&page_size=6`;
    if (cat) url += `&category=${encodeURIComponent(cat)}`;
    if (currentFeedApplicability && currentFeedApplicability !== "ALL") {
        url += `&applicability=${encodeURIComponent(currentFeedApplicability)}`;
    }

    try {
        const res = await fetch(url);
        const data = await res.json();

        // Update tier counts badges if returned
        if (data.tier_counts) {
            const tc = data.tier_counts;
            const bAll = document.getElementById("badgeAll");
            const bApp = document.getElementById("badgeApplicable");
            const bRel = document.getElementById("badgeRelevant");
            const bUrg = document.getElementById("badgeUrgent");
            const bDln = document.getElementById("badgeDeadlines");
            const bGen = document.getElementById("badgeGeneral");

            if (bAll) bAll.textContent = data.total_items !== undefined ? data.total_items : (data.total || "--");
            if (bApp) bApp.textContent = tc.DEFINITELY_APPLICABLE || 0;
            if (bRel) bRel.textContent = tc.POTENTIALLY_RELEVANT || 0;
            if (bUrg) bUrg.textContent = tc.URGENT || 0;
            if (bDln) bDln.textContent = tc.UPCOMING_DEADLINES || 0;
            if (bGen) bGen.textContent = tc.GENERAL_NOTICE || 0;
        }

        if (!data.feed || data.feed.length === 0) {
            feedContainer.innerHTML = `<div class="empty-state">No personalized announcements found for this filter combination.</div>`;
            return;
        }

        feedContainer.innerHTML = data.feed.map(item => renderNoticeCard(item, true)).join("");
        renderPagination(data.page, data.total_pages, "loadPersonalizedFeed");
    } catch (e) {
        feedContainer.innerHTML = `<div class="error-state">Error loading feed: ${e.message}</div>`;
    }
}

function renderNoticeCard(item, showRelevance = false) {
    const urgencyClass = `badge-${(item.urgency || 'LOW').toLowerCase()}`;
    const attachWarning = item.attachment_present ?
        `<div class="attachment-warning">📎 Attachment Referenced: ${item.attachment_names ? item.attachment_names.join(", ") : 'Attachment File'} (Note: Actual file contents are unavailable)</div>` : '';

    const explanation = showRelevance && item.explanation ?
        `<div class="explanation-banner">🎯 Priority Score: ${(item.personal_priority_score * 100).toFixed(0)}% • ${item.explanation}</div>` : '';

    const isUms = item.source && item.source.startsWith('ums');
    const umsBadge = isUms ?
        `<span class="badge badge-ums-live">🏛️ UMS Live</span>` : '';
    
    const umsLink = item.source_url ?
        `<a href="${item.source_url}" target="_blank" onclick="event.stopPropagation()" style="color:var(--accent-color); font-size:12px; margin-left:8px;">Open in UMS ↗</a>` : '';

    // Impact Type Badge — visually distinguishes exemptions from events
    let impactBadge = '';
    if (item.impact_type) {
        const impactLabels = {
            'ROOM_EXEMPTION': '🚫 Rooms Exempted',
            'ROOM_UNAVAILABLE': '🔒 Rooms Unavailable',
            'BLOCK_RESTRICTION': '⛔ Block Restricted',
            'CLASS_CANCELLATION': '❌ Class Cancelled',
            'VENUE_CHANGE': '🔄 Venue Changed',
            'EVENT_LOCATION': '📍 Event Location (NOT exemption)',
            'ROOM_MENTION_ONLY': '💬 Room Mentioned',
            'UNKNOWN_IMPACT': ''
        };
        const label = impactLabels[item.impact_type] || '';
        if (label) {
            const impactClass = item.impact_type === 'ROOM_EXEMPTION' ? 'badge-critical' :
                item.impact_type === 'EVENT_LOCATION' ? 'badge-low' : 'badge-high';
            impactBadge = `<span class="badge ${impactClass}" style="font-size:10px;">${label}</span>`;
        }
    }

    // Applicability Tier Badge
    let tierBadge = '';
    if (item.applicability_tier) {
        switch (item.applicability_tier) {
            case "DEFINITELY_APPLICABLE":
                tierBadge = `<span class="badge badge-applicable">🎯 Applicable</span>`;
                break;
            case "POTENTIALLY_RELEVANT":
                tierBadge = `<span class="badge badge-relevant">💡 Relevant</span>`;
                break;
            case "GENERAL_NOTICE":
                tierBadge = `<span class="badge badge-general">📢 General</span>`;
                break;
            case "NOT_APPLICABLE":
                tierBadge = `<span class="badge badge-low">🚫 Excluded</span>`;
                break;
            case "UNCERTAIN":
                tierBadge = `<span class="badge badge-high">❓ Uncertain</span>`;
                break;
        }
    }

    // Deadline Badge
    let deadlineBadge = '';
    if (item.deadline_date) {
        if (item.is_deadline_expired) {
            deadlineBadge = `<span class="badge badge-deadline-expired">⛔ Deadline Expired: ${item.deadline_date}</span>`;
        } else {
            const daysText = item.days_remaining !== null && item.days_remaining !== undefined ? ` (${item.days_remaining}d left)` : '';
            deadlineBadge = `<span class="badge badge-deadline-active">⏳ Due: ${item.deadline_date}${daysText}</span>`;
        }
    }

    return `
        <div class="notice-card" onclick="viewAnnouncement('${item.announcement_id}')">
            <div class="card-header">
                <div class="notice-title">${item.title}</div>
                <div class="badge-group">
                    ${impactBadge}
                    ${umsBadge}
                    ${tierBadge}
                    ${deadlineBadge}
                    <span class="badge ${urgencyClass}">${item.urgency || 'NOTICE'}</span>
                    <span class="badge badge-low">${item.category || 'GENERAL'}</span>
                </div>
            </div>
            ${explanation}
            ${attachWarning}
            <div class="notice-snippet">${(item.full_content || item.document || '').substring(0, 200)}...</div>
            <div class="card-footer">
                <span>📅 Published: ${item.publication_date} | Ref: ${item.reference_number || 'N/A'}${umsLink}</span>
                <div>
                    <button class="feedback-btn" onclick="event.stopPropagation(); submitFeedback('${item.announcement_id}', true)">👍 Relevant</button>
                    <button class="feedback-btn" onclick="event.stopPropagation(); submitFeedback('${item.announcement_id}', false)">👎 Not Relevant</button>
                </div>
            </div>
        </div>
    `;
}

// ==========================================================================
// Grounded RAG Chatbot State & Handlers
// ==========================================================================
let chatHistory = [];
let isChatSubmitting = false;

function formatAssistantAnswer(text) {
    if (!text) return "";
    let html = text
        // Bold formatting
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        // Source citation inline clickable badges
        .replace(/\[Source ID:\s*([^\]]+)\]/g, (match, id) => {
            const cleanId = id.trim();
            return `<button class="inline-citation" onclick="viewAnnouncement('${cleanId}')" title="Click to view announcement ${cleanId}">📄 ${cleanId}</button>`;
        })
        // Bullet points
        .replace(/^\s*[\*\-]\s+(.*)$/gm, '<li>$1</li>')
        // Numbered list items
        .replace(/^\s*(\d+)\.\s+(.*)$/gm, '<li><strong>$1.</strong> $2</li>');

    // Group adjacent <li> items into a styled <ul>
    html = html.replace(/(<li>.*?<\/li>\s*)+/gs, (match) => `<ul class="chat-bullet-list">${match}</ul>`);
    // Preserve paragraphs and line breaks
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/(?<!<\/li>)\n/g, '<br>');

    return html;
}

async function handleChatSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (isChatSubmitting) return;

    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("chatSendBtn");
    const query = input.value.trim();
    if (!query) return;

    const savedQuery = query;
    isChatSubmitting = true;
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = `Thinking... ⏳`;
    }
    input.disabled = true;

    // Render user message and clear input
    appendChatMessage("user", query);
    input.value = "";

    const chatContainer = document.getElementById("chatMessages");
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "message assistant-message";
    loadingMsg.id = "chatLoading";
    loadingMsg.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="message-body chat-loading-body">
            <span>Analyzing announcements and retrieving grounded evidence</span>
            <div class="loading-dots"><span>.</span><span>.</span><span>.</span></div>
        </div>
    `;
    chatContainer.appendChild(loadingMsg);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const payload = {
            query: savedQuery,
            student_id: activeStudentId,
            history: chatHistory.slice(-8),
            top_k: 15
        };

        const res = await fetch("/api/v1/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errJson = await res.json().catch(() => ({}));
            const detailMsg = errJson.detail || `Server error (${res.status}: ${res.statusText})`;
            throw new Error(detailMsg);
        }

        const data = await res.json();
        const loadingElem = document.getElementById("chatLoading");
        if (loadingElem) loadingElem.remove();

        const formatted = formatAssistantAnswer(data.answer);
        let answerHtml = `<div class="chat-answer-content">${formatted}</div>`;

        if (data.attachment_warning) {
            answerHtml += `<div class="attachment-warning" style="margin-top:12px;">⚠️ ${data.attachment_warning}</div>`;
        }

        if (data.sources && data.sources.length > 0) {
            answerHtml += `<div class="chat-citations-header">📚 Grounded Sources & Citations (${data.sources.length}):</div>`;
            answerHtml += `<div class="chat-citations-list">`;
            data.sources.forEach(s => {
                const liveBadge = s.source && s.source.startsWith('ums') ? '<span class="badge badge-ums-live" style="margin-left:6px; font-size:10px;">🏛️ UMS Live</span>' : '';
                const umsUrlBtn = s.source_url ? `<a href="${s.source_url}" target="_blank" onclick="event.stopPropagation()" class="citation-external-link">↗ Portal</a>` : '';
                answerHtml += `
                    <div class="source-card-citation" onclick="viewAnnouncement('${s.announcement_id}')" style="cursor:pointer;" title="Click to view full notice">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <div>
                                <strong>[Source ID: ${s.announcement_id}]</strong>${liveBadge} ${s.title} (${s.publication_date})
                            </div>
                            ${umsUrlBtn}
                        </div>
                        <div style="margin-top:4px; font-size:11px; color:var(--text-muted);">
                            Relevance: ${(s.similarity_score * 100).toFixed(1)}% | Evidence Completeness: <strong>${s.decision_completeness}</strong>
                        </div>
                    </div>
                `;
            });
            answerHtml += `</div>`;
        }

        appendChatMessage("assistant", answerHtml, true);

        // Record in conversation history for multi-turn follow-ups
        chatHistory.push({ role: "user", content: savedQuery });
        chatHistory.push({ role: "assistant", content: data.answer });
        if (chatHistory.length > 12) chatHistory = chatHistory.slice(-12);

    } catch (err) {
        const loadingElem = document.getElementById("chatLoading");
        if (loadingElem) loadingElem.remove();

        // Restore query so user doesn't lose text
        input.value = savedQuery;

        const errorHtml = `
            <div class="chat-error-card">
                <strong>⚠️ Failed to get response</strong>
                <p style="margin:4px 0 8px 0; font-size:13px; color:#fca5a5;">${err.message}</p>
                <button class="btn btn-secondary retry-chat-btn" onclick="retryChatQuery(${JSON.stringify(savedQuery).replace(/"/g, '&quot;')})">
                    🔄 Retry Query
                </button>
            </div>
        `;
        appendChatMessage("assistant", errorHtml, true);
    } finally {
        isChatSubmitting = false;
        input.disabled = false;
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = `Send 🚀`;
        }
        input.focus();
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

function retryChatQuery(queryText) {
    const input = document.getElementById("chatInput");
    input.value = queryText;
    handleChatSubmit(new Event("submit", { cancelable: true }));
}

function appendChatMessage(role, content, isHtml = false) {
    const chatContainer = document.getElementById("chatMessages");
    const msg = document.createElement("div");
    msg.className = `message ${role}-message`;
    const avatar = role === "assistant" ? "🤖" : "👨‍🎓";

    msg.innerHTML = `
        <div class="avatar">${avatar}</div>
        <div class="message-body">${isHtml ? content : `<p>${content}</p>`}</div>
    `;
    chatContainer.appendChild(msg);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function sendQuickChat(queryText) {
    const input = document.getElementById("chatInput");
    input.value = queryText;
    handleChatSubmit(new Event("submit", { cancelable: true }));
}

function clearChatHistory() {
    chatHistory = [];
    const chatContainer = document.getElementById("chatMessages");
    chatContainer.innerHTML = `
        <div class="message assistant-message">
            <div class="avatar">🤖</div>
            <div class="message-body">
                <p>Chat history cleared. How can I assist you with LPU announcements today?</p>
                <div class="sample-chips">
                    <button class="chip" onclick="sendQuickChat('When are 3rd year B.Tech exams starting?')">When are 3rd year B.Tech exams starting?</button>
                    <button class="chip" onclick="sendQuickChat('Are there placement drives for Software Engineers?')">Are there placement drives for Software Engineers?</button>
                    <button class="chip" onclick="sendQuickChat('What announcements affect Block 34?')">What announcements affect Block 34?</button>
                </div>
            </div>
        </div>
    `;
}

let currentSearchPage = 1;

async function executeSearch(page = 1) {
    currentSearchPage = page;
    const qInput = document.getElementById("searchInput");
    const q = qInput ? qInput.value.trim() : "";
    if (!q) {
        document.getElementById("searchResults").innerHTML = `<div class="empty-state">Please enter a search keyword or room number.</div>`;
        return;
    }

    const resContainer = document.getElementById("searchResults");
    resContainer.innerHTML = `<div class="loading-spinner">Searching announcements for "${q}"...</div>`;

    const cat = document.getElementById("searchCategorySelect") ? document.getElementById("searchCategorySelect").value : "";
    const urg = document.getElementById("searchUrgencySelect") ? document.getElementById("searchUrgencySelect").value : "";
    const sort = document.getElementById("searchSortSelect") ? document.getElementById("searchSortSelect").value : "relevance";
    const attOnly = document.getElementById("searchAttachmentOnly") ? document.getElementById("searchAttachmentOnly").checked : false;

    let url = `/api/v1/announcements/search?q=${encodeURIComponent(q)}&page=${page}&page_size=8&sort_by=${encodeURIComponent(sort)}`;
    if (cat) url += `&category=${encodeURIComponent(cat)}`;
    if (urg) url += `&urgency=${encodeURIComponent(urg)}`;
    if (attOnly) url += `&attachment_only=true`;

    try {
        const res = await fetch(url);
        const data = await res.json();

        if (!data.results || data.results.length === 0) {
            resContainer.innerHTML = `<div class="empty-state">No announcements matched your search criteria. Try different keywords.</div>`;
            document.getElementById("searchPagination").innerHTML = "";
            return;
        }

        resContainer.innerHTML = data.results.map(item => renderNoticeCard(item, false)).join("");
        renderPagination(data.page, data.total_pages, "executeSearch", "searchPagination");
    } catch (e) {
        resContainer.innerHTML = `<div class="error-state">Search error: ${e.message}</div>`;
    }
}

function resetSearchFilters() {
    const sInput = document.getElementById("searchInput");
    if (sInput) sInput.value = "";
    const cat = document.getElementById("searchCategorySelect");
    if (cat) cat.value = "";
    const urg = document.getElementById("searchUrgencySelect");
    if (urg) urg.value = "";
    const sort = document.getElementById("searchSortSelect");
    if (sort) sort.value = "relevance";
    const att = document.getElementById("searchAttachmentOnly");
    if (att) att.checked = false;

    document.getElementById("searchResults").innerHTML = `<div class="empty-state">Enter a query above to search announcements.</div>`;
    document.getElementById("searchPagination").innerHTML = "";
}

let cachedTimetableImpacts = [];
let currentTimetableFilter = "ALL";

function filterTimetable(filterType, evt) {
    currentTimetableFilter = filterType;
    document.querySelectorAll("#timetableFilters .pill-btn").forEach(btn => btn.classList.remove("active"));
    if (evt && evt.currentTarget) evt.currentTarget.classList.add("active");
    renderFilteredTimetable();
}

function renderFilteredTimetable() {
    const container = document.getElementById("timetableList");
    let filtered = cachedTimetableImpacts;

    if (currentTimetableFilter === "AFFECTED") {
        filtered = cachedTimetableImpacts.filter(i => i.affected && i.status !== "EXEMPTED" && i.status !== "ATTACHMENT_DEPENDENT");
    } else if (currentTimetableFilter === "EXEMPTED") {
        filtered = cachedTimetableImpacts.filter(i => i.status === "EXEMPTED");
    } else if (currentTimetableFilter === "ATTACHMENT") {
        filtered = cachedTimetableImpacts.filter(i => i.status === "ATTACHMENT_DEPENDENT");
    } else if (currentTimetableFilter === "CLEAR") {
        filtered = cachedTimetableImpacts.filter(i => !i.affected && i.status !== "EXEMPTED");
    }

    if (!filtered || filtered.length === 0) {
        container.innerHTML = `<div class="empty-state">No timetable entries matching "${currentTimetableFilter}".</div>`;
        return;
    }

    container.innerHTML = filtered.map(imp => {
        let borderColor = '#3fb950'; // Green
        let statusBadgeClass = 'badge-medium';
        if (imp.status === "CONFIRMED_MATCH") {
            borderColor = '#f85149'; // Red
            statusBadgeClass = 'badge-critical';
        } else if (imp.status === "EXEMPTED") {
            borderColor = '#38bdf8'; // Blue
            statusBadgeClass = 'badge-low';
        } else if (imp.status === "ATTACHMENT_DEPENDENT") {
            borderColor = '#f59e0b'; // Amber
            statusBadgeClass = 'badge-high';
        } else if (imp.status === "POTENTIAL_IMPACT") {
            borderColor = '#d946ef'; // Magenta
            statusBadgeClass = 'badge-high';
        }

        const impactTypeTag = imp.impact_type && imp.impact_type !== "NONE" ?
            `<span class="badge" style="background:rgba(255,255,255,0.08); font-size:11px; margin-left:6px;">${imp.impact_type}</span>` : '';

        return `
            <div class="notice-card" style="border-left:4px solid ${borderColor}">
                <div class="card-header">
                    <div>
                        <strong>Class: ${imp.entry.course_code} — ${imp.entry.course_name}</strong><br>
                        <span style="font-size:12px; color:var(--text-secondary);">Room: ${imp.entry.room} | Date: ${imp.entry.day_or_date} (${imp.entry.start_time} - ${imp.entry.end_time}) | Building: ${imp.entry.building || 'Campus'}</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:4px;">
                        ${impactTypeTag}
                        <span class="badge ${statusBadgeClass}">${imp.status}</span>
                    </div>
                </div>
                <div style="font-size:13px; color:var(--text-primary); margin-top:8px;">${imp.explanation}</div>
                ${imp.evidence_text ? `<div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">🔍 Evidence: <em>${imp.evidence_text}</em></div>` : ''}
                ${imp.announcement_title ? `<div style="font-size:12px; color:var(--accent-color); margin-top:6px; cursor:pointer;" onclick="viewAnnouncement('${imp.announcement_id}')">Related Notice: "${imp.announcement_title}" ↗</div>` : ''}
            </div>
        `;
    }).join("");
}

async function loadAffectedClasses() {
    const container = document.getElementById("timetableList");
    container.innerHTML = `<div class="loading-spinner">Checking room & timetable conflict analysis for ${activeStudentId}...</div>`;

    try {
        const res = await fetch(`/api/v1/feed/${activeStudentId}/affected-classes`);
        const data = await res.json();
        cachedTimetableImpacts = data.impacts || [];

        // Update counts
        const allCount = cachedTimetableImpacts.length;
        const affCount = cachedTimetableImpacts.filter(i => i.affected && i.status !== "EXEMPTED" && i.status !== "ATTACHMENT_DEPENDENT").length;
        const exCount = cachedTimetableImpacts.filter(i => i.status === "EXEMPTED").length;
        const attCount = cachedTimetableImpacts.filter(i => i.status === "ATTACHMENT_DEPENDENT").length;
        const clrCount = cachedTimetableImpacts.filter(i => !i.affected && i.status !== "EXEMPTED").length;

        const elAll = document.getElementById("ttCountAll");
        const elAff = document.getElementById("ttCountAffected");
        const elEx = document.getElementById("ttCountExempted");
        const elAtt = document.getElementById("ttCountAttachment");
        const elClr = document.getElementById("ttCountClear");

        if (elAll) elAll.textContent = allCount;
        if (elAff) elAff.textContent = affCount;
        if (elEx) elEx.textContent = exCount;
        if (elAtt) elAtt.textContent = attCount;
        if (elClr) elClr.textContent = clrCount;

        renderFilteredTimetable();
    } catch (e) {
        container.innerHTML = `<div class="error-state">Error analyzing timetable: ${e.message}</div>`;
    }
}

async function triggerCacheReload() {
    try {
        const res = await fetch("/api/v1/health/cache-refresh", { method: "POST" });
        const data = await res.json();
        alert(`⚡ ${data.message || "Cache reloaded successfully!"}`);
        loadHealthDashboard();
    } catch (e) {
        alert("Failed to reload cache: " + e.message);
    }
}

async function loadHealthDashboard() {
    try {
        const res = await fetch("/api/v1/health");
        const data = await res.json();

        // Update Subsystem chips
        if (data.subsystems) {
            const sqText = document.getElementById("sqliteStatusText");
            const chText = document.getElementById("chromaStatusText");
            const gmText = document.getElementById("geminiStatusText");

            if (sqText) {
                sqText.textContent = data.subsystems.sqlite === "healthy" ? "Connected 🟢" : "Error 🔴";
                sqText.style.color = data.subsystems.sqlite === "healthy" ? "#34d399" : "#f87171";
            }
            if (chText) {
                chText.textContent = data.subsystems.chromadb === "healthy" ? "Indexed 🟢" : "Degraded 🟡";
                chText.style.color = data.subsystems.chromadb === "healthy" ? "#34d399" : "#fbbf24";
            }
            if (gmText) {
                gmText.textContent = data.subsystems.gemini_api === "configured" ? "Online 🟢" : "Offline Vectors 🟡";
                gmText.style.color = data.subsystems.gemini_api === "configured" ? "#38bdf8" : "#fbbf24";
            }
        }

        document.getElementById("metricTotal").textContent = (data.dataset_summary && data.dataset_summary.total_records) || 0;
        document.getElementById("metricAttachments").textContent = (data.dataset_summary && data.dataset_summary.with_attachments) || 0;
        document.getElementById("metricIndexed").textContent = (data.vector_index_summary && data.vector_index_summary.total_indexed_documents) || 0;
        document.getElementById("metricModel").textContent = data.generation_model || "Gemini";

        document.getElementById("datasetReportPre").textContent = JSON.stringify(data.dataset_summary, null, 2);
        document.getElementById("indexStatusPre").textContent = JSON.stringify(data.vector_index_summary, null, 2);

        // Fetch UMS Sync history
        loadUmsHistory();

        // Fetch pipeline diagnostics
        loadPipelineDiagnostics();
    } catch (e) {
        console.error("Error loading dashboard metrics:", e);
    }
}

async function loadPipelineDiagnostics() {
    const container = document.getElementById("pipelineDiagnosticsPre");
    if (!container) return;

    try {
        const res = await fetch("/api/v1/diagnostics/pipeline");
        if (!res.ok) return;
        const data = await res.json();

        const statusBreakdown = data.processing_status_breakdown || {};
        const statusLines = Object.entries(statusBreakdown).map(([status, count]) => `${status}: ${count}`).join(" | ");

        const summary = {
            "Raw Live Records": data.raw_live_records,
            "Historical Records": data.historical_records,
            "Total Corpus": data.total_corpus_records,
            "Extracted Metadata": data.extracted_metadata_records,
            "Live w/ Metadata": data.live_with_extracted_metadata,
            "ChromaDB Indexed": data.chromadb_indexed_count,
            "Coverage Gap": data.coverage_gap,
            "Processing Status": statusBreakdown,
            "Recent Live IDs": data.recent_live_ids,
            "Recent Indexed": data.recent_live_indexed,
            "Recent Not Indexed": data.recent_live_not_indexed,
        };
        container.textContent = JSON.stringify(summary, null, 2);
    } catch (e) {
        container.textContent = "Error loading diagnostics: " + e.message;
    }
}

async function loadUmsStatus() {
    try {
        const res = await fetch("/api/v1/ums/status");
        if (!res.ok) return;
        const data = await res.json();
        
        const badge = document.getElementById("umsStatusBadge");
        const lastSync = document.getElementById("umsLastSyncText");
        if (!badge || !lastSync) return;

        badge.className = "ums-status-badge";
        if (data.connector_mode === "mock") {
            badge.classList.add("mock");
            badge.textContent = "Mock Mode";
        } else if (data.status === "LIVE_CONNECTED" || (data.connection_check && data.connection_check.connected)) {
            badge.classList.add("connected");
            badge.textContent = "Official Live Feed Active 🟢";
        } else if (data.status === "AUTH_REQUIRED") {
            badge.classList.add("auth_required");
            badge.textContent = "Auth Required";
        } else {
            badge.classList.add("error");
            badge.textContent = (data.connection_check && data.connection_check.status) || "Offline";
        }

        if (data.connector_mode === "live") {
            const radioLive = document.getElementById("modeRadioLive");
            if (radioLive) radioLive.checked = true;
        } else {
            const radioMock = document.getElementById("modeRadioMock");
            if (radioMock) radioMock.checked = true;
        }

        if (data.last_sync && data.last_sync.completed_at) {
            const dateStr = new Date(data.last_sync.completed_at).toLocaleTimeString();
            lastSync.textContent = `Last Synced: ${dateStr} (${data.last_sync.status})`;
        } else {
            lastSync.textContent = `Last Synced: Never`;
        }
    } catch (e) {
        console.error("Failed to load UMS status:", e);
    }
}

async function triggerUmsSync() {
    const btn = document.getElementById("umsSyncBtn");
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="loading-spin">⏳</span> Syncing notices...`;

    try {
        const res = await fetch("/api/v1/ums/sync?limit=20", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const result = await res.json();
        if (res.ok) {
            if (result.inserted_count > 0 || result.updated_count > 0) {
                btn.innerHTML = `✅ Synced (${result.inserted_count} new, ${result.updated_count} rev)`;
            } else if (result.skipped_count > 0) {
                btn.innerHTML = `⚡ Up to Date (${result.skipped_count} current)`;
            } else {
                btn.innerHTML = `ℹ️ ${result.status || "0 notices"}`;
            }
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }, 3500);
            loadPersonalizedFeed();
            loadUmsStatus();
            loadHealthDashboard();
        } else {
            alert(`Sync notice: ${result.detail || "Unable to sync."}`);
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    } catch (e) {
        alert(`Sync error: ${e.message}`);
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function loadUmsHistory() {
    const container = document.getElementById("umsSyncHistoryContent");
    if (!container) return;

    try {
        const res = await fetch("/api/v1/ums/sync/history?limit=5");
        const history = await res.json();
        if (!history || history.length === 0) {
            container.innerHTML = `<p style="color:var(--text-secondary); font-size:13px;">No synchronization runs logged yet. Click 'Sync UMS Notices' to run initial sync.</p>`;
            return;
        }

        container.innerHTML = `
            <table class="sync-history-table">
                <thead>
                    <tr>
                        <th>Sync ID</th>
                        <th>Started At</th>
                        <th>Status</th>
                        <th>Fetched</th>
                        <th>New</th>
                        <th>Updated</th>
                        <th>Skipped</th>
                        <th>Indexed</th>
                        <th>Result</th>
                        <th>Triggered By</th>
                    </tr>
                </thead>
                <tbody>
                    ${history.map(h => `
                        <tr>
                            <td><code>${h.sync_id}</code></td>
                            <td>${new Date(h.started_at).toLocaleTimeString()}</td>
                            <td><span class="badge ${h.status === 'SUCCESS' ? 'badge-medium' : (h.status === 'UP_TO_DATE' ? 'badge-low' : 'badge-critical')}">${h.status}</span></td>
                            <td>${h.fetched_count}</td>
                            <td><strong style="color:var(--accent-color);">${h.inserted_count}</strong></td>
                            <td>${h.updated_count}</td>
                            <td>${h.skipped_count}</td>
                            <td>${h.indexed_count !== undefined ? h.indexed_count : '-'}</td>
                            <td style="font-size:11px; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${h.message || ''}">${h.message || (h.error_message ? 'Error: ' + h.error_message : 'Completed')}</td>
                            <td>${h.triggered_by}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    } catch (e) {
        container.innerHTML = `<p style="color:var(--text-secondary);">Error loading sync history: ${e.message}</p>`;
    }
}

async function viewAnnouncement(id) {
    try {
        const res = await fetch(`/api/v1/announcements/${id}`);
        const ann = await res.json();

        const modalBody = document.getElementById("modalBody");
        modalBody.innerHTML = `
            <h2>${ann.title}</h2>
            <p style="font-size:12px; color:var(--text-secondary); margin-bottom:16px;">
                ID: ${ann.announcement_id} | Ref: ${ann.reference_number || 'N/A'} | Published: ${ann.publication_date}
            </p>
            ${ann.attachment_present ? `<div class="attachment-warning">📎 Attachment Referenced: ${ann.attachment_names.join(", ")}<br><small>(Contents unavailable in database)</small></div>` : ''}
            <div style="background:var(--bg-primary); padding:16px; border-radius:8px; font-size:14px; white-space:pre-wrap; margin-bottom:16px; border:1px solid var(--border-color);">
                ${ann.full_content}
            </div>
            ${ann.metadata ? `
                <div style="font-size:12px; color:var(--text-secondary);">
                    <strong>Extracted Metadata:</strong> Category: ${ann.metadata.category} | Urgency: ${ann.metadata.urgency} | Action Type: ${ann.metadata.action_type} | Decision Completeness: ${ann.metadata.decision_completeness}
                </div>
            ` : ''}
        `;
        document.getElementById("announcementModal").style.display = "flex";
    } catch (e) {
        alert("Failed to load announcement details: " + e.message);
    }
}

function closeModal() {
    document.getElementById("announcementModal").style.display = "none";
}

async function submitFeedback(announcementId, isRelevant) {
    try {
        await fetch("/api/v1/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                student_id: activeStudentId,
                announcement_id: announcementId,
                is_relevant: isRelevant
            })
        });
        alert(isRelevant ? "Marked as Relevant 👍" : "Marked as Not Relevant 👎");
    } catch (e) {
        console.error("Feedback error:", e);
    }
}

function renderPagination(page, totalPages, fetchFuncStr) {
    const container = document.getElementById("feedPagination");
    if (totalPages <= 1) {
        container.innerHTML = "";
        return;
    }
    container.innerHTML = `
        <button class="btn btn-secondary" ${page === 1 ? 'disabled' : ''} onclick="${fetchFuncStr}(${page - 1})">Previous</button>
        <span style="font-size:13px; color:var(--text-secondary);">Page ${page} of ${totalPages}</span>
        <button class="btn btn-secondary" ${page === totalPages ? 'disabled' : ''} onclick="${fetchFuncStr}(${page + 1})">Next</button>
    `;
}

function openUmsSetupModal() {
    updateSyncSnippetDisplay();
    document.getElementById("umsSetupModal").style.display = "flex";
}

function closeUmsSetupModal() {
    document.getElementById("umsSetupModal").style.display = "none";
}

function switchSetupTab(tabId) {
    const pTab = document.getElementById("setupTabPaste");
    const bTab = document.getElementById("setupTabBrowser");
    const cTab = document.getElementById("setupTabCookie");
    if (pTab) pTab.style.display = tabId === 'pasteTab' ? 'block' : 'none';
    if (bTab) bTab.style.display = tabId === 'browserTab' ? 'block' : 'none';
    if (cTab) cTab.style.display = tabId === 'cookieTab' ? 'block' : 'none';

    const bp = document.getElementById("tabBtnPaste");
    const bb = document.getElementById("tabBtnBrowser");
    const bc = document.getElementById("tabBtnCookie");
    if (bp) bp.className = 'nav-item ' + (tabId === 'pasteTab' ? 'active' : '');
    if (bb) bb.className = 'nav-item ' + (tabId === 'browserTab' ? 'active' : '');
    if (bc) bc.className = 'nav-item ' + (tabId === 'cookieTab' ? 'active' : '');
}

function loadSampleLiveNotice() {
    const sample = `Title: End Term Examination & Practical Evaluation Schedule Autumn 2026
Reference Number: LPU/10.2/EXAM/2026/0149
Date: 16-10-2026
Full Content:
All 2nd and 3rd Year B.Tech Computer Science and Engineering students are hereby notified that the Autumn 2026 End Term Practical Examinations will be conducted from 10th November to 20th November 2026.
The laboratory venue for course CSE301 (Data Structures) will be Block 34, Computer Lab 34-204 and 34-205.
Students must report 15 minutes prior to session commencement and bring university ID cards.
Attachment: End_Term_Practical_DateSheet_2026.pdf`;
    const input = document.getElementById("pastedNoticeInput");
    if (input) input.value = sample;
}

async function submitPastedNotice() {
    const input = document.getElementById("pastedNoticeInput");
    const text = input ? input.value.trim() : "";
    if (!text) {
        alert("Please paste announcement text, table rows, or HTML from UMS.");
        return;
    }

    const btn = document.getElementById("pasteIngestBtn");
    const originalText = btn ? btn.innerHTML : "Ingest";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="loading-spin">⏳</span> Ingesting into SmartNotice...`;
    }

    try {
        const res = await fetch("/api/v1/ums/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_text: text })
        });
        const result = await res.json();
        if (res.ok) {
            let msg = "";
            if (result.inserted_count > 0) {
                msg = `🎉 Success! Ingested ${result.inserted_count} new real-time announcement(s) into SmartNotice!`;
            } else if (result.skipped_count > 0) {
                msg = `⚡ All ${result.skipped_count} announcement(s) are already up to date in SmartNotice!`;
            } else if (result.updated_count > 0) {
                msg = `🔄 Updated ${result.updated_count} revised announcement(s)!`;
            } else {
                msg = `ℹ️ ${result.message || "Ingested notices."}`;
            }
            alert(msg);
            if (input) input.value = "";
            closeUmsSetupModal();
            loadPersonalizedFeed();
            loadUmsStatus();
            loadHealthDashboard();
        } else {
            alert(`Import failed: ${result.detail || JSON.stringify(result)}`);
        }
    } catch (e) {
        alert("Error ingesting notices: " + e.message);
    } finally {
        if (btn) {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
}

function updateSyncSnippetDisplay() {
    const el = document.getElementById("consoleSnippet");
    if (!el) return;
    const origin = window.location.origin;
    el.innerText = `(async()=>{try{let n=[];const parseDate=(txt)=>{if(!txt)return null;const m1=txt.match(/\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s*(\\d{1,2})[\\s,]+(\\d{4})\\b/i);if(m1){const months={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};const mNum=String(months[m1[1].slice(0,3).toLowerCase()]||1).padStart(2,'0');const day=String(m1[2]).padStart(2,'0');return \`\${m1[3]}-\${mNum}-\${day}\`;}const m2=txt.match(/\\b(\\d{1,2})[-/\\s](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/\\s](\\d{4})\\b/i);if(m2){const months={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};const mNum=String(months[m2[2].slice(0,3).toLowerCase()]||1).padStart(2,'0');const day=String(m2[1]).padStart(2,'0');return \`\${m2[3]}-\${mNum}-\${day}\`;}const m3=txt.match(/\\b(\\d{4})-(\\d{2})-(\\d{2})\\b/);if(m3)return m3[0];return null;};const ep=['/lpuums/StudentDashboard.aspx/AnnouncementDetails','/lpuums/frmStudentDashboard.aspx/AnnouncementDetails'];for(const u of ep){try{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json;charset=utf-8'},body:JSON.stringify({pageSize:50})});if(r.ok){const d=await r.json(),i=d.d||d;const raw=typeof i==='string'?JSON.parse(i):i;const list=Array.isArray(raw)?raw:(raw.Table||raw.announcements||raw.data||raw.items||[]);if(Array.isArray(list)&&list.length){n=list;break;}}}catch(e){}}if(!n.length){const candidates=Array.from(document.querySelectorAll('div, li, tr')).filter(el=>{const t=el.innerText||'';return /LPU\\/\\d+|REF|ANN/i.test(t)&&t.length>40&&t.length<5000&&el.querySelectorAll('div, li, tr').length<5;});candidates.forEach((el,idx)=>{const text=el.innerText.trim();const dateMatch=parseDate(text);const refMatch=text.match(/\\(([^)]*(?:LPU|ANN|REF)[^)]*)\\)/i)||text.match(/(?:LPU|REF|ANN)[\\w\\/\\(\\)\\.\\-]+/i);const ref=refMatch?(refMatch[1]||refMatch[0]).trim():\`UMS-NOTICE-\${idx+1}\`;let lines=text.split('\\n').map(l=>l.trim()).filter(Boolean);let titleLine=lines[0]||'UMS Announcement';titleLine=titleLine.replace(/^New\\s+/i,'').replace(/\\s*\\([^)]*(?:LPU|ANN|REF)[^)]*\\)\\s*/i,'').replace(/\\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s*\\d{1,2}[\\s,]+\\d{4}\\b/i,'').trim();n.push({title:titleLine||lines[0],full_content:text,publication_date:dateMatch||new Date().toISOString().slice(0,10),reference_number:ref});});}if(!n.length){document.querySelectorAll('table tbody tr').forEach((tr,i)=>{const c=Array.from(tr.querySelectorAll('td')).map(td=>td.innerText.trim()).filter(Boolean);if(c.length>=2){const d=parseDate(c.join(' '))||new Date().toISOString().slice(0,10);const ref=c.find(x=>/LPU|REF|ANN/i.test(x))||('UMS-ROW-'+(i+1));n.push({title:c[1]||c[0],full_content:c.join('\\n'),publication_date:d,reference_number:ref});}});}if(!n.length){n=[{title:document.title||'UMS Announcement',full_content:document.body.innerText.slice(0,4000),publication_date:new Date().toISOString().slice(0,10),reference_number:'UMS-LIVE-'+Date.now()}];}const endpoint='${origin}/api/v1/ums/import';let synced=false;try{const res=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({announcements:n})});if(res.ok){const resJson=await res.json();synced=true;let msg='';if(resJson.inserted_count>0){msg='🎉 Successfully synced '+resJson.inserted_count+' new notices into LPU SmartNotice!'+(resJson.updated_count?' ('+resJson.updated_count+' revised)':'');}else if(resJson.skipped_count>0){msg='⚡ All '+resJson.skipped_count+' announcements are already up to date in SmartNotice! (0 new, '+resJson.skipped_count+' current)';}else if(resJson.updated_count>0){msg='🔄 Updated '+resJson.updated_count+' revised announcement(s) in SmartNotice!';}else{msg='ℹ️ '+(resJson.message||'Sync completed.');}alert(msg);}}catch(netErr){}if(!synced){try{await navigator.clipboard.writeText(JSON.stringify({announcements:n}));alert('⚡ Extracted '+n.length+' announcements from UMS!\\n\\nNote: Direct background fetch was blocked by browser security (Mixed Content or CSP).\\n\\n✅ All announcements are now COPIED to your clipboard!\\nReturn to SmartNotice -> "Paste Notices" tab, press Ctrl+V, and click Ingest.');}catch(clipErr){alert('⚠️ Sync error: direct fetch failed and clipboard copy was blocked.');}}}catch(err){alert('⚠️ Scraping error: '+err.message);}})();`;
}

function copyConsoleSnippet() {
    updateSyncSnippetDisplay();
    const text = document.getElementById("consoleSnippet").innerText;
    navigator.clipboard.writeText(text).then(() => {
        alert(`📋 Copied 1-click sync snippet for ${window.location.origin}!\n\nNow open your ums.lpu.in tab, press F12 -> Console, paste and hit Enter.`);
    }).catch(err => {
        alert("Clipboard copy failed: " + err);
    });
}

async function submitManualCookie() {
    const cookieInput = document.getElementById("manualCookieInput");
    const cookie = cookieInput ? cookieInput.value.trim() : "";
    const modeLive = document.getElementById("modeRadioLive");
    const mode = (modeLive && modeLive.checked) ? "live" : "mock";

    const payload = { mode: mode };
    if (cookie) {
        payload.cookie = cookie;
    }

    try {
        const res = await fetch("/api/v1/ums/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (res.ok) {
            let msg = "";
            if (result.inserted_count > 0) {
                msg = `🎉 Settings saved! Synced ${result.inserted_count} new announcement(s) into SmartNotice!`;
            } else if (result.skipped_count > 0) {
                msg = `⚡ Settings saved! All ${result.skipped_count} announcements are already up to date!`;
            } else if (result.updated_count > 0) {
                msg = `🔄 Settings saved! Updated ${result.updated_count} revised announcement(s)!`;
            } else {
                msg = `ℹ️ Settings saved: ${result.message || "Ready."}`;
            }
            alert(msg);
            closeUmsSetupModal();
            loadPersonalizedFeed();
            loadUmsStatus();
            loadHealthDashboard();
        } else {
            alert(`Portal notice: ${result.detail || JSON.stringify(result)}`);
        }
    } catch (e) {
        alert("Failed to update settings: " + e.message);
    }
}

// --- Custom Student Management & Timetable Modal ---
function openAddStudentModal() {
    const modal = document.getElementById("addStudentModal");
    if (!modal) return;
    modal.style.display = "flex";
    const container = document.getElementById("timetableRowsContainer");
    if (container && container.children.length === 0) {
        addTimetableRow({
            day_or_date: "2026-10-27",
            start_time: "09:00 AM",
            end_time: "10:00 AM",
            course_code: "CSE301",
            course_name: "Data Structures & Algorithms",
            room: "34-105",
            faculty: "Dr. Sharma"
        });
    }
}

function closeAddStudentModal() {
    const modal = document.getElementById("addStudentModal");
    if (modal) modal.style.display = "none";
}

let timetableRowCount = 0;
function addTimetableRow(data = {}) {
    timetableRowCount++;
    const container = document.getElementById("timetableRowsContainer");
    if (!container) return;

    const rowId = `ttRow_${timetableRowCount}`;
    const row = document.createElement("div");
    row.id = rowId;
    row.className = "tt-row-item";
    row.innerHTML = `
        <input type="text" class="tt-day" placeholder="Day / Date" value="${data.day_or_date || '2026-10-27'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); outline: none;" title="Day of week or ISO date (e.g. 2026-10-27 or Monday)">
        <input type="text" class="tt-start" placeholder="Start" value="${data.start_time || '09:00 AM'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); outline: none;" title="Start Time">
        <input type="text" class="tt-end" placeholder="End" value="${data.end_time || '10:00 AM'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); outline: none;" title="End Time">
        <input type="text" class="tt-code" placeholder="Code" value="${data.course_code || 'CSE301'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); outline: none;" title="Course Code (e.g. CSE301)">
        <input type="text" class="tt-name" placeholder="Course Title" value="${data.course_name || 'Data Structures'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); outline: none;" title="Course Name">
        <input type="text" class="tt-room" placeholder="Room" value="${data.room || '34-105'}" style="padding: 7px 10px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); font-weight: 600; outline: none;" title="Room Number (e.g. 34-105 or 34304X or 14106)">
        <button type="button" onclick="document.getElementById('${rowId}').remove()" style="background: transparent; border: none; color: #f87171; font-size: 18px; cursor: pointer; text-align: center;" title="Remove Row">&times;</button>
    `;
    container.appendChild(row);
}

function loadSampleTimetableRows() {
    const container = document.getElementById("timetableRowsContainer");
    if (!container) return;
    container.innerHTML = "";
    const samples = [
        { day_or_date: "2026-10-27", start_time: "09:00 AM", end_time: "10:00 AM", course_code: "CSE301", course_name: "Data Structures & Algorithms", room: "34-105" },
        { day_or_date: "2026-10-27", start_time: "11:00 AM", end_time: "12:00 PM", course_code: "INT219", course_name: "Front End Web Development", room: "34-108" },
        { day_or_date: "2026-10-27", start_time: "02:00 PM", end_time: "03:00 PM", course_code: "CSE316", course_name: "Operating Systems Lab", room: "14106" },
        { day_or_date: "2026-10-28", start_time: "10:00 AM", end_time: "11:00 AM", course_code: "MTH202", course_name: "Discrete Mathematics", room: "33303" }
    ];
    samples.forEach(s => addTimetableRow(s));
}

async function submitNewStudent(event) {
    if (event) event.preventDefault();

    const stuId = document.getElementById("newStudentId").value.trim();
    const name = document.getElementById("newStudentName").value.trim();
    const program = document.getElementById("newStudentProgram").value.trim();
    const dept = document.getElementById("newStudentDept").value.trim();
    const year = parseInt(document.getElementById("newStudentYear").value) || 1;
    const sem = parseInt(document.getElementById("newStudentSem").value) || 1;
    const section = document.getElementById("newStudentSection").value.trim();
    const school = document.getElementById("newStudentSchool").value.trim();
    const interestsRaw = document.getElementById("newStudentInterests").value.trim();
    const careerGoal = document.getElementById("newStudentCareerGoal").value.trim();

    if (!stuId || !name || !program) {
        alert("Please provide Registration Number, Name, and Stream/Program.");
        return;
    }

    const interests = interestsRaw ? interestsRaw.split(",").map(s => s.trim()).filter(Boolean) : ["Academics", "Placements"];

    // Collect timetable rows
    const rows = document.querySelectorAll("#timetableRowsContainer .tt-row-item");
    const timetable = [];
    rows.forEach(r => {
        const d = r.querySelector(".tt-day").value.trim();
        const start = r.querySelector(".tt-start").value.trim();
        const end = r.querySelector(".tt-end").value.trim();
        const code = r.querySelector(".tt-code").value.trim();
        const cname = r.querySelector(".tt-name").value.trim();
        const room = r.querySelector(".tt-room").value.trim();

        if (code && room) {
            timetable.push({
                day_or_date: d || "Monday",
                start_time: start || "09:00 AM",
                end_time: end || "10:00 AM",
                course_code: code,
                course_name: cname || code,
                room: room
            });
        }
    });

    const payload = {
        student_id: stuId,
        name: name,
        program: program,
        department: dept,
        school: school,
        year: year,
        semester: sem,
        section: section,
        interests: interests,
        career_goal: careerGoal,
        timetable: timetable
    };

    const btn = document.getElementById("saveStudentBtn");
    const originalText = btn ? btn.innerHTML : "Save";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = "Saving...";
    }

    try {
        const res = await fetch("/api/v1/students", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to create student");
        }

        alert(`🎉 ${data.message || "Student created successfully!"}`);
        closeAddStudentModal();

        // Reload students and switch context to newly created student
        activeStudentId = stuId;
        await loadStudents();
        const select = document.getElementById("studentSelector");
        if (select) select.value = stuId;
        updateStudentCard();
        loadPersonalizedFeed();
    } catch (err) {
        alert("Error saving student: " + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}


