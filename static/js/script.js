// Global variable to store bidDocumentNumber and downloadFilename
let globalBidDocumentNumber = '';
let globalDownloadFilename = ''; // New variable to store the filename for download
let chatHistory = [];
let chatReady = false;
let chatSessionId = generateChatSessionId();
let isChatProcessing = false;
let latestReportHtml = '';
let latestGapScore = null;
let latestDifferencePercentage = null;
let latestProposalStatus = '';
let enhancedProposalAllowed = false;
let enhancedProposalFilename = '';

// Dashboard elements for quick status overview
const dashboardElements = {
    bidNumber: document.getElementById('dashboardBidNumber'),
    gapScore: document.getElementById('dashboardGapScore'),
    difference: document.getElementById('dashboardDifference'),
    status: document.getElementById('dashboardStatus'),
    statusBadge: document.getElementById('dashboardStatusBadge'),
    statusCard: document.getElementById('dashboardStatusCard')
};

const DASHBOARD_TONES = {
    neutral: {
        statusClasses: ['text-slate-900'],
        badgeClasses: ['bg-slate-200', 'text-slate-700'],
        cardClasses: ['border-slate-200', 'bg-slate-50']
    },
    accepted: {
        statusClasses: ['text-emerald-700'],
        badgeClasses: ['bg-emerald-100', 'text-emerald-800'],
        cardClasses: ['border-emerald-200', 'bg-emerald-50']
    },
    rejected: {
        statusClasses: ['text-rose-700'],
        badgeClasses: ['bg-rose-100', 'text-rose-800'],
        cardClasses: ['border-rose-200', 'bg-rose-50']
    }
};

const ALL_STATUS_CLASSES = ['text-slate-900', 'text-emerald-700', 'text-rose-700'];
const ALL_BADGE_CLASSES = [
    'bg-slate-200', 'text-slate-700',
    'bg-emerald-100', 'text-emerald-800',
    'bg-rose-100', 'text-rose-800'
];
const ALL_CARD_CLASSES = [
    'border-slate-200', 'bg-slate-50',
    'border-emerald-200', 'bg-emerald-50',
    'border-rose-200', 'bg-rose-50'
];

function updateDashboard({ bidNumber = '--', gapScore = '--', difference = '--%', status = '--', tone = 'neutral' }) {
    if (!dashboardElements.bidNumber) {
        return; // Dashboard not present; avoid runtime errors
    }

    dashboardElements.bidNumber.textContent = bidNumber || '--';

    const gapScoreValue = (gapScore !== undefined && gapScore !== null) ? gapScore : '--';
    dashboardElements.gapScore.textContent = gapScoreValue;

    const differenceValue = (difference !== undefined && difference !== null) ? difference : '--%';
    dashboardElements.difference.textContent = differenceValue;

    const statusValue = status || '--';
    dashboardElements.status.textContent = statusValue;

    const toneConfig = DASHBOARD_TONES[tone] || DASHBOARD_TONES.neutral;

    dashboardElements.status.classList.remove(...ALL_STATUS_CLASSES);
    dashboardElements.status.classList.add(...toneConfig.statusClasses);

    dashboardElements.statusBadge.classList.remove(...ALL_BADGE_CLASSES);
    dashboardElements.statusBadge.classList.add(...toneConfig.badgeClasses);
    dashboardElements.statusBadge.textContent = statusValue || 'Awaiting Analysis';

    dashboardElements.statusCard.classList.remove(...ALL_CARD_CLASSES);
    dashboardElements.statusCard.classList.add(...toneConfig.cardClasses);
}

function generateChatSessionId() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return `chat-${Date.now()}`;
}

function setChatStatus(message, isError = false) {
    const chatStatus = document.getElementById('chatStatus');
    if (!chatStatus) return;
    chatStatus.textContent = message;
    chatStatus.classList.toggle('text-red-600', isError);
    chatStatus.classList.toggle('text-gray-500', !isError);
}

function appendChatMessage(role, text) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;

    const wrapper = document.createElement('div');
    wrapper.className = `mb-4 flex ${role === 'user' ? 'justify-end' : 'justify-start'}`;

    const bubble = document.createElement('div');
    bubble.className = `rounded-lg px-4 py-2 max-w-[90%] text-sm ${
        role === 'user' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-900'
    }`;
    bubble.textContent = text;

    wrapper.appendChild(bubble);
    chatContainer.appendChild(wrapper);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function resetChatPanel(disableButton = true) {
    chatHistory = [];
    chatSessionId = generateChatSessionId();
    isChatProcessing = false;

    const chatContainer = document.getElementById('chatMessages');
    const chatInput = document.getElementById('chatInput');
    const sendChatBtn = document.getElementById('sendChatBtn');

    if (chatContainer) {
        chatContainer.innerHTML = '<div class="text-gray-500 text-sm">Ask questions about the generated report or uploaded files once they are processed.</div>';
    }
    if (chatInput) {
        chatInput.value = '';
    }
    if (sendChatBtn && disableButton) {
        sendChatBtn.disabled = true;
    }

    chatReady = !disableButton;
    setChatStatus('Process documents and generate a report to enable chat.');
}

function resetEnhancedProposalPanel() {
    enhancedProposalAllowed = false;
    enhancedProposalFilename = '';
    latestGapScore = null;
    latestDifferencePercentage = null;
    latestProposalStatus = '';
    const statusEl = document.getElementById('enhancedProposalStatus');
    const displayEl = document.getElementById('enhancedProposalDisplay');
    const writeBtn = document.getElementById('writeProposalBtn');
    const downloadBtn = document.getElementById('downloadProposalBtn');

    if (statusEl) {
        statusEl.textContent = 'Generate a report to see if an enhanced proposal is recommended.';
        statusEl.classList.remove('text-red-600');
        statusEl.classList.add('text-gray-600');
    }
    if (displayEl) {
        displayEl.innerHTML = '<p class="text-gray-500 text-sm">Once available, the AI-generated enhanced proposal will appear here.</p>';
    }
    [writeBtn, downloadBtn].forEach(btn => {
        if (btn) {
            btn.classList.add('hidden');
            btn.disabled = true;
        }
    });
}

function updateEnhancedProposalState({ allowed = false, message = '' }) {
    const statusEl = document.getElementById('enhancedProposalStatus');
    const writeBtn = document.getElementById('writeProposalBtn');
    const downloadBtn = document.getElementById('downloadProposalBtn');

    enhancedProposalAllowed = allowed;
    if (!statusEl || !writeBtn || !downloadBtn) {
        return;
    }

    statusEl.textContent = message || (allowed
        ? 'A refreshed proposal is recommended.'
        : 'Enhanced proposal generation is not required yet.');
    statusEl.classList.toggle('text-red-600', allowed);
    statusEl.classList.toggle('text-gray-600', !allowed);

    if (allowed) {
        writeBtn.classList.remove('hidden');
        writeBtn.disabled = false;
    } else {
        writeBtn.classList.add('hidden');
        writeBtn.disabled = true;
        downloadBtn.classList.add('hidden');
        downloadBtn.disabled = true;
    }
}

function enableChatPanel(message) {
    const sendChatBtn = document.getElementById('sendChatBtn');
    if (sendChatBtn) {
        sendChatBtn.disabled = false;
    }
    chatReady = true;
    setChatStatus(message || 'Chat ready. Ask questions about your documents.');
}

async function sendChatMessage() {
    if (!chatReady || isChatProcessing) {
        setChatStatus('Please process your documents and ensure the chat is ready.', true);
        return;
    }

    const chatInput = document.getElementById('chatInput');
    if (!chatInput) return;

    const message = chatInput.value.trim();
    if (!message) {
        return;
    }

    if (!globalBidDocumentNumber) {
        setChatStatus('Add a Bid Document Number and process documents before chatting.', true);
        return;
    }

    const historyPayload = chatHistory.slice(-8);
    appendChatMessage('user', message);
    chatHistory.push({ role: 'user', content: message });
    chatInput.value = '';

    const sendChatBtn = document.getElementById('sendChatBtn');
    if (sendChatBtn) {
        sendChatBtn.disabled = true;
    }
    isChatProcessing = true;
    setChatStatus('Analyzing the report and retrieved documents...');

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message,
                bidDocumentNumber: globalBidDocumentNumber,
                reportHtml: latestReportHtml,
                sessionId: chatSessionId,
                history: historyPayload
            })
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Unable to retrieve an answer.');
        }

        const answerText = (result.answer || '').trim() || 'No response generated.';
        appendChatMessage('assistant', answerText);
        chatHistory.push({ role: 'assistant', content: answerText });

        setChatStatus('Ask another question or refine your request.');
    } catch (error) {
        appendChatMessage('assistant', `Error: ${error.message}`);
        setChatStatus('Unable to chat right now. Please try again.', true);
    } finally {
        isChatProcessing = false;
        if (sendChatBtn) {
            sendChatBtn.disabled = !chatReady;
        }
    }
}

// Function to reset the UI state
function resetUI() {
    const processBtn = document.getElementById('processBtn');
    const processingStatus = document.getElementById('processingStatus');
    const processingSpinner = document.getElementById('processingSpinner');
    const generateReportBtn = document.getElementById('generateReportBtn');
    const downloadReportBtn = document.getElementById('downloadReportBtn'); // Get the new button
    const reportDiv = document.getElementById('report');

    processBtn.disabled = false;
    processBtn.classList.remove('opacity-50', 'cursor-not-allowed', 'hidden');
    processingSpinner.classList.add('hidden');
    processingStatus.classList.add('hidden');
    processingStatus.textContent = '';
    generateReportBtn.classList.add('hidden');
    downloadReportBtn.classList.add('hidden'); // Hide download button on reset
    reportDiv.innerHTML = '<p class="text-gray-500">Upload documents and process them to generate a report.</p>';

    globalDownloadFilename = ''; // Clear stored filename on reset
    latestReportHtml = '';
    resetEnhancedProposalPanel();
    resetChatPanel(true);
    updateDashboard({}); // Reset dashboard to default values
}

// Call resetUI on page load to ensure clean state
document.addEventListener('DOMContentLoaded', resetUI);

// --- Process Documents Function ---
async function processDocuments() {
    const form = document.getElementById('uploadForm');
    const formData = new FormData(form);

    globalBidDocumentNumber = document.getElementById('bidDocumentNumber').value.trim();
    formData.append('bidDocumentNumber', globalBidDocumentNumber);

    const rfpFile = document.getElementById('rfpFile').files[0];
    const responseFile = document.getElementById('responseFile').files[0];

    if (!globalBidDocumentNumber || !rfpFile || !responseFile) {
        alert("Please fill in Bid Document Number and upload both RFP and Response PDF files.");
        return;
    }

    updateDashboard({
        bidNumber: globalBidDocumentNumber,
        gapScore: '--',
        difference: '--%',
        status: 'Processing…',
        tone: 'neutral'
    });

    const processBtn = document.getElementById('processBtn');
    const processingStatus = document.getElementById('processingStatus');
    const processingSpinner = document.getElementById('processingSpinner');

    processBtn.disabled = true;
    processBtn.classList.add('opacity-50', 'cursor-not-allowed');
    processingSpinner.classList.remove('hidden');
    processingStatus.classList.remove('hidden', 'bg-red-50', 'text-red-700', 'bg-green-50', 'text-green-700');
    processingStatus.classList.add('bg-blue-50', 'text-blue-700');
    processingStatus.textContent = 'Processing documents... This may take a moment.';

    try {
        const response = await fetch('/process', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (response.ok) {
            processingStatus.classList.remove('bg-blue-50', 'text-blue-700', 'bg-red-50', 'text-red-700');
            processingStatus.classList.add('bg-green-50', 'text-green-700');
            processingStatus.textContent = result.message || 'Documents processed successfully!';
            processBtn.classList.add('hidden');
            document.getElementById('generateReportBtn').classList.remove('hidden');

            updateDashboard({
                bidNumber: globalBidDocumentNumber,
                gapScore: '--',
                difference: '--%',
                status: 'Ready for Report',
                tone: 'neutral'
            });

            resetChatPanel(true);
            latestReportHtml = '';
            enableChatPanel('Chat is ready. Generate the report for deeper answers, or start asking about the uploaded files now.');
            resetEnhancedProposalPanel();

            const bodyElement = document.querySelector('body');
            if (bodyElement && bodyElement.__alpine && bodyElement.__alpine.$data) {
                bodyElement.__alpine.$data.activeTab = 'report';
            } else {
                console.warn("Alpine.js data not found on body element. Cannot set activeTab.");
            }

        } else {
            throw new Error(result.error || 'An error occurred while processing documents.');
        }
    } catch (error) {
        processingStatus.classList.remove('bg-blue-50', 'text-blue-700', 'bg-green-50', 'text-green-700');
        processingStatus.classList.add('bg-red-50', 'text-red-700');
        processingStatus.textContent = `Error: ${error.message}`;

        processBtn.disabled = false;
        processBtn.classList.remove('opacity-50', 'cursor-not-allowed');

        updateDashboard({
            bidNumber: globalBidDocumentNumber || '--',
            gapScore: '--',
            difference: '--%',
            status: 'Processing Failed',
            tone: 'rejected'
        });
    } finally {
        processingSpinner.classList.add('hidden');
    }
}

// --- Generate Report Function ---
async function generateReport() {
    const generateReportBtn = document.getElementById('generateReportBtn');
    const downloadReportBtn = document.getElementById('downloadReportBtn'); // Get the new button
    const reportDiv = document.getElementById('report');
    const statusPopup = document.getElementById('statusPopup');

    generateReportBtn.disabled = true;
    generateReportBtn.classList.add('opacity-50', 'cursor-not-allowed');
    reportDiv.innerHTML = 'Generating report... <svg class="animate-spin h-5 w-5 text-indigo-500 inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

    updateDashboard({
        bidNumber: globalBidDocumentNumber || '--',
        gapScore: '--',
        difference: '--%',
        status: 'Scoring…',
        tone: 'neutral'
    });

    try {
        const response = await fetch('/generate_report', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ bidDocumentNumber: globalBidDocumentNumber })
        });
        const result = await response.json();

        if (response.ok) {
            const statusValue = result.proposal_status || 'Processed';
            const differenceValue = (typeof result.difference_percentage === 'number')
                ? `${result.difference_percentage.toFixed(2)}%`
                : 'N/A';

            statusPopup.textContent = `Proposal ${statusValue}! (${differenceValue} difference)`;
            if (statusValue === "Rejected") {
                statusPopup.classList.add('rejected');
            } else {
                statusPopup.classList.add('accepted');
            }
            statusPopup.style.display = 'block';
            statusPopup.classList.add('show');

            // Store the download filename
            globalDownloadFilename = result.download_filename;

            const sanitizedBidNumber = result.bid_document_number || globalBidDocumentNumber || '--';
            const gapScoreDisplay = (typeof result.gap_score === 'number') ? result.gap_score : '--';
            const tone = statusValue.toLowerCase() === 'rejected' ? 'rejected' : 'accepted';
            latestGapScore = typeof result.gap_score === 'number' ? result.gap_score : null;
            latestDifferencePercentage = typeof result.difference_percentage === 'number' ? result.difference_percentage : null;
            latestProposalStatus = statusValue;

            updateDashboard({
                bidNumber: sanitizedBidNumber,
                gapScore: gapScoreDisplay,
                difference: differenceValue,
                status: statusValue,
                tone
            });

            if ('allow_enhanced_proposal' in result) {
                updateEnhancedProposalState({
                    allowed: Boolean(result.allow_enhanced_proposal),
                    message: result.enhanced_proposal_message || ''
                });
            }

            setTimeout(() => {
                statusPopup.classList.remove('show');
                setTimeout(() => {
                    statusPopup.style.display = 'none';
                    statusPopup.classList.remove('rejected', 'accepted');
                    reportDiv.innerHTML = result.structured_report;
                    latestReportHtml = result.structured_report || '';
                    enableChatPanel('Chat now includes the generated report for richer answers.');
                    generateReportBtn.classList.add('hidden');

                    // Show the download button after report is generated
                    downloadReportBtn.classList.remove('hidden');

                    // Re-enable process button and clear status after report is shown
                    const processBtn = document.getElementById('processBtn');
                    const processingStatus = document.getElementById('processingStatus');
                    processBtn.disabled = false;
                    processBtn.classList.remove('opacity-50', 'cursor-not-allowed', 'hidden');
                    processingStatus.classList.add('hidden');
                }, 500);
            }, 4000);

        } else {
            throw new Error(result.error || 'An error occurred while generating the report');
        }
    } catch (error) {
        reportDiv.innerHTML = `<div class="bg-red-50 border-l-4 border-red-400 p-4 text-red-700" role="alert">Error: ${error.message}</div>`;
        generateReportBtn.disabled = false;
        generateReportBtn.classList.remove('opacity-50', 'cursor-not-allowed');

        updateDashboard({
            bidNumber: globalBidDocumentNumber || '--',
            gapScore: '--',
            difference: '--%',
            status: 'Report Failed',
            tone: 'rejected'
        });

        const processBtn = document.getElementById('processBtn');
        processBtn.disabled = false;
        processBtn.classList.remove('opacity-50', 'cursor-not-allowed', 'hidden');
    }
}

// --- Download Report Function ---
function downloadReport() {
    if (globalDownloadFilename) {
        // Create a temporary anchor tag
        const a = document.createElement('a');
        a.href = `/download/${globalDownloadFilename}`; // Construct the download URL
        a.download = globalDownloadFilename; // Suggest the filename for download
        document.body.appendChild(a); // Append to body (required for Firefox)
        a.click(); // Programmatically click the anchor
        document.body.removeChild(a); // Clean up
    } else {
        alert('No report file available for download. Please generate a report first.');
    }
}

async function writeEnhancedProposal() {
    if (!enhancedProposalAllowed) {
        updateEnhancedProposalState({ allowed: false, message: 'Enhanced proposals are only available when the evaluation recommends it.' });
        return;
    }
    if (!globalBidDocumentNumber || !latestReportHtml) {
        updateEnhancedProposalState({ allowed: false, message: 'Process documents and generate a report before drafting a new proposal.' });
        return;
    }

    const writeBtn = document.getElementById('writeProposalBtn');
    const downloadBtn = document.getElementById('downloadProposalBtn');
    const displayEl = document.getElementById('enhancedProposalDisplay');
    const statusEl = document.getElementById('enhancedProposalStatus');

    if (!writeBtn || !displayEl || !statusEl || !downloadBtn) {
        return;
    }

    writeBtn.disabled = true;
    statusEl.textContent = 'Drafting a new proposal based on the latest analysis...';
    statusEl.classList.remove('text-red-600');
    statusEl.classList.add('text-gray-600');
    displayEl.innerHTML = '<p class="text-sm text-gray-600">Generating proposal... <svg class="animate-spin h-4 w-4 inline text-orange-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg></p>';
    downloadBtn.classList.add('hidden');
    downloadBtn.disabled = true;

    try {
        const response = await fetch('/enhanced_proposal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                bidDocumentNumber: globalBidDocumentNumber,
                reportHtml: latestReportHtml,
                gapScore: latestGapScore,
                differencePercentage: latestDifferencePercentage,
                proposalStatus: latestProposalStatus
            })
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Unable to draft the enhanced proposal.');
        }

        const proposalHtml = result.proposal_html || '<p>No proposal content was generated.</p>';
        enhancedProposalFilename = result.download_filename || '';
        displayEl.innerHTML = proposalHtml;

        if (enhancedProposalFilename) {
            downloadBtn.classList.remove('hidden');
            downloadBtn.disabled = false;
        }

        statusEl.textContent = 'Enhanced proposal ready. Review and download as needed.';
    } catch (error) {
        statusEl.textContent = `Unable to generate enhanced proposal: ${error.message}`;
        statusEl.classList.remove('text-gray-600');
        statusEl.classList.add('text-red-600');
        displayEl.innerHTML = `<div class="text-red-600 text-sm">${error.message}</div>`;
    } finally {
        writeBtn.disabled = !enhancedProposalAllowed;
    }
}

function downloadEnhancedProposal() {
    if (enhancedProposalFilename) {
        const a = document.createElement('a');
        a.href = `/download/${enhancedProposalFilename}`;
        a.download = enhancedProposalFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    } else {
        alert('No enhanced proposal available. Generate one first.');
    }
}
