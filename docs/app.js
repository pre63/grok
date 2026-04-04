if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then(registration => console.log('Service Worker registered:', registration))
      .catch(error => console.log('Service Worker registration failed:', error))
  })
}

mermaid.initialize({ startOnLoad: false })

const messagesDiv = document.getElementById('messages')
const input = document.getElementById('input')
const sendBtn = document.getElementById('sendBtn')
const expertBtn = document.getElementById('expertBtn')
const modelSelect = document.getElementById('modelSelect')
const chatHistory = document.getElementById('chatHistory')
const newChatBtn = document.getElementById('newChatBtn')
const authPopup = document.getElementById('authPopup')
const usernameInput = document.getElementById('username')
const passwordInput = document.getElementById('password')
const authBtn = document.getElementById('authBtn')
const menuBtn = document.getElementById('menuBtn')
const overlay = document.getElementById('overlay')
const sidebar = document.querySelector('.sidebar')

let conversation = []
let lastUserMessage = null
let currentChatId = null
let chats = [] // ← stays in memory after first load

// Persist model selection
modelSelect.value = localStorage.getItem('selectedModel') || 'grok-4-1-fast-reasoning'
modelSelect.addEventListener('change', () =>
  localStorage.setItem('selectedModel', modelSelect.value))

// ====================== URL → Chat ID logic ======================
function getChatIdFromUrl() {
  const path = window.location.pathname
  if (path.startsWith('/chat/')) return path.slice(6)
  if (path === '/new' || path === '/') return null
  return null
}

function updateUrlWithChatId(chatId) {
  if (!chatId) {
    history.replaceState(null, '', '/new')
    return
  }
  history.replaceState(null, '', `/chat/${chatId}`)
}

// ====================== AUTH ======================
async function checkAuth() {
  const token = localStorage.getItem('jwt')
  if (!token) {
    authPopup.style.display = 'flex'
    return false
  }
  const response = await fetch('/verify', {
    headers: { Authorization: `Bearer ${token}` }
  })
  if (!response.ok) {
    localStorage.removeItem('jwt')
    authPopup.style.display = 'flex'
    return false
  }
  return true
}

async function handleAuth() {
  const username = usernameInput.value.trim()
  const password = passwordInput.value.trim()
  if (!username || !password) {
    alert('Please enter username and password')
    return
  }
  const response = await fetch('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  if (response.ok) {
    const { token } = await response.json()
    localStorage.setItem('jwt', token)
    authPopup.style.display = 'none'
    initApp()
  } else {
    const err = await response.json().catch(() => ({}))
    alert(err.error || 'Login failed')
  }
}
authBtn.onclick = handleAuth

// ====================== CHAT HISTORY (now stays in memory) ======================
async function loadChatHistory() {
  const token = localStorage.getItem('jwt')
  const response = await fetch('/chats', {
    headers: { Authorization: `Bearer ${token}` }
  })
  if (response.ok) {
    chats = await response.json() // stored in memory
    renderChatHistory()
  }
}
function renderChatHistory() {
  chatHistory.innerHTML = ''
  chats.forEach(chat => {
    const li = document.createElement('li')

    const titleLink = document.createElement('a')
    titleLink.textContent = chat.title || 'Untitled Chat'
    titleLink.href = `/chat/${chat.id}`
    li.appendChild(titleLink)

    const deleteBtn = document.createElement('button')
    deleteBtn.classList.add('delete-btn')
    const deleteSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    deleteSvg.setAttribute('viewBox', '0 0 24 24')
    deleteSvg.setAttribute('width', '16')
    deleteSvg.setAttribute('height', '16')
    deleteSvg.innerHTML =
      '<path d="M3 6h18v2H3V6zm3 3h12v12a2 2 0 01-2 2H8a2 2 0 01-2-2V9zm3-6h6v2H9V3z" fill="currentColor"/>'
    deleteBtn.appendChild(deleteSvg)
    deleteBtn.onclick = e => {
      e.stopImmediatePropagation()
      li.remove()
      deleteChat(chat.id)
    }
    li.appendChild(deleteBtn)
    chatHistory.appendChild(li)
  })
}

async function deleteChat(chatId) {
  const token = localStorage.getItem('jwt')
  const response = await fetch(`/chat/${chatId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` }
  })
  if (response.ok) {
    if (currentChatId === chatId) newChat()
    await loadChatHistory() // only refresh when deleted
  } else {
    alert('Failed to delete chat')
  }
}

function closeSidebar() {
  if (window.matchMedia('(max-width: 768px)').matches) {
    sidebar.classList.remove('open')
    overlay.style.display = 'none'
  }
}

// ====================== LOAD CHAT ======================
async function loadChat(chatId) {
  currentChatId = chatId
  const token = localStorage.getItem('jwt')
  const response = await fetch(`/chat/${chatId}`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  if (response.ok) {
    const data = await response.json()
    conversation = data.messages || []
    messagesDiv.innerHTML = ''
    conversation.forEach(msg => {
      appendMessage(msg.role === 'user' ? 'User' : 'Grok', msg.content)
    })
    closeSidebar()
  }
}

// ====================== SAVE CHAT (no longer refreshes history every message) ======================
async function saveChat() {
  if (!currentChatId) return
  const token = localStorage.getItem('jwt')
  await fetch(`/chat/${currentChatId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ messages: conversation })
  })
  await loadChatHistory()
}

// ====================== STREAM API ======================
async function streamApi(
  messages,
  model = 'grok-4-1-fast-reasoning',
  temperature = 0.7,
  maxTokens = 8192,
  useTools = true,
  chat_id = null,
  onData
) {
  const token = localStorage.getItem('jwt')
  const response = await fetch('/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      model,
      messages,
      temperature,
      max_tokens: maxTokens,
      stream: true,
      use_tools: useTools,
      ...(chat_id && { chat_id })
    })
  })

  if (!response.ok) throw new Error('API request failed')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const dataStr = line.slice(6)
        if (dataStr === '[DONE]') continue
        try {
          const parsed = JSON.parse(dataStr)
          onData(parsed)
        } catch (e) {}
      }
    }
  }
}

// ====================== RENDERING (unchanged) ======================
function markdownToHtml(text) {
  const converter = new showdown.Converter({
    tables: true,
    tasklists: true,
    ghCodeBlocks: true,
    simplifiedAutoLink: true,
    strikethrough: true,
    emoji: true
  })
  return converter.makeHtml(text)
}
async function renderContent(text, element, isUser = false) {
  if (isUser) {
    element.textContent = text // Plain text for user messages
    return
  }

  const delimiters = [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '$', right: '$', display: false },
    { left: '\\(', right: '\\)', display: false }]

  let result = ''
  let i = 0
  const len = text.length

  while (i < len) {
    let foundDelim = null
    let minStart = len
    for (const delim of delimiters) {
      const start = text.indexOf(delim.left, i)
      if (start !== -1 && start < minStart) {
        minStart = start
        foundDelim = delim
      }
    }

    if (foundDelim === null) {
      result += text.slice(i)
      break
    }

    result += text.slice(i, minStart)
    i = minStart + foundDelim.left.length

    let nest = 1
    let j = i
    while (j < len && nest > 0) {
      if (text.slice(j, j + foundDelim.left.length) === foundDelim.left) {
        nest++
        j += foundDelim.left.length
      } else if (text.slice(j, j + foundDelim.right.length) === foundDelim.right) {
        nest--
        j += foundDelim.right.length
      } else {
        j++
      }
    }

    if (nest > 0) {
      result += foundDelim.left + text.slice(i)
      break
    }

    const math = text.slice(i, j - foundDelim.right.length)
    let rendered
    try {
      rendered = katex.renderToString(math, {
        throwOnError: false,
        displayMode: foundDelim.display
      })
    } catch (err) {
      rendered = foundDelim.left + math + foundDelim.right
    }
    result += rendered

    i = j
  }

  const html = markdownToHtml(result)
  element.innerHTML = DOMPurify.sanitize(html)

  // Highlight code blocks
  element.querySelectorAll('pre code').forEach(block => {
    const lang = block.className.match(/language-(\w+)/)?.[1]
    if (lang === 'mermaid') {
      const id =
        'mermaid-' +
        Math.random()
          .toString(36)
          .substr(2, 9)
      block.id = id
      mermaid.run({ nodes: [block] }).catch(err => console.error('Mermaid error:', err))
    } else {
      hljs.highlightElement(block)
    }
    // Add copy button to code blocks
    const copyButton = document.createElement('button')
    copyButton.className = 'action-btn button copy-code'
    copyButton.innerHTML =
      '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 4a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2H8zm-6 4h4v10H2V8zm14 2h4v6h-4v-6z"/></svg>'
    copyButton.onclick = () => {
      navigator.clipboard.writeText(block.innerText)
      copyButton.innerHTML =
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 4v2h6V4h2v2h1a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h1V4h2zm8 4H7v10h10V8zM9 10h2v2H9v-2zm4 0h2v2h-2v-2zm-4 4h2v2H9v-2zm4 0h2v2h-2v-2z"/></svg>'
      setTimeout(
        () =>
          (copyButton.innerHTML =
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 4a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2H8zm-6 4h4v10H2V8zm14 2h4v6h-4v-6z"/></svg>'),
        2000
      )
    }
    block.parentNode.insertBefore(copyButton, block)
  })
}

function appendMessage(roleLabel, content, isEdit = false) {
  const messageDiv = document.createElement('div')
  messageDiv.classList.add('message', roleLabel.toLowerCase())

  const contentElem = document.createElement('div')
  contentElem.classList.add('content')
  renderContent(content, contentElem, roleLabel === 'User')
  messageDiv.appendChild(contentElem)

  // Add actions
  const actions = document.createElement('div')
  actions.classList.add('message-actions')
  if (roleLabel === 'Grok') {
    // Regenerate
    const regenerateSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    regenerateSvg.setAttribute('viewBox', '0 0 24 24')
    regenerateSvg.setAttribute('width', '24') // Explicit size to avoid shrinking
    regenerateSvg.setAttribute('height', '24')
    regenerateSvg.setAttribute('fill', 'none') // No fill for outline icons
    regenerateSvg.setAttribute('stroke', 'currentColor')
    regenerateSvg.setAttribute('stroke-width', '2')
    regenerateSvg.setAttribute('stroke-linecap', 'round')
    regenerateSvg.setAttribute('stroke-linejoin', 'round')

    regenerateSvg.innerHTML = `
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.79 2.89"/>
      <path d="M21 3v6h-6"/>
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.79-2.89"/>
      <path d="M3 21v-6h6"/>
    `

    regenerateSvg.classList.add('action-icon', 'svg-button')
    regenerateSvg.onclick = () => regenerateMessage(messageDiv)
    actions.appendChild(regenerateSvg)
  } else {
    // Edit
    const editSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    editSvg.setAttribute('viewBox', '0 0 24 24')
    editSvg.setAttribute('width', '24') // Add explicit size
    editSvg.setAttribute('height', '24')
    editSvg.setAttribute('fill', 'none') // Crucial for outline icons
    editSvg.setAttribute('stroke', 'currentColor')
    editSvg.setAttribute('stroke-width', '2')
    editSvg.setAttribute('stroke-linecap', 'round')
    editSvg.setAttribute('stroke-linejoin', 'round')

    editSvg.innerHTML = `
  <path d="M12 20h9"/>
  <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
`

    editSvg.classList.add('action-icon', 'svg-button')
    editSvg.onclick = () => editMessage(messageDiv, roleLabel)
    actions.appendChild(editSvg)
  }

  // Copy
  const copySvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  copySvg.setAttribute('viewBox', '0 0 24 24')
  copySvg.setAttribute('width', '24') // Keeps it visible and sized
  copySvg.setAttribute('height', '24')
  copySvg.setAttribute('fill', 'none')
  copySvg.setAttribute('stroke', 'currentColor')
  copySvg.setAttribute('stroke-width', '2')
  copySvg.setAttribute('stroke-linecap', 'round')
  copySvg.setAttribute('stroke-linejoin', 'round')

  copySvg.innerHTML = `
    <path d="M8 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2h-2"/>
    <path d="M16 4H8a2 2 0 0 0-2 2v13h12V6a2 2 0 0 0-2-2z"/>
  `

  copySvg.classList.add('action-icon', 'svg-button')
  copySvg.onclick = () => copyMessage(messageDiv) // Adjust function name/args as needed
  actions.appendChild(copySvg)

  messageDiv.appendChild(actions)

  messagesDiv.appendChild(messageDiv)
  messagesDiv.scrollTop = messagesDiv.scrollHeight
  return messageDiv
}

function editMessage(messageDiv, roleLabel) {
  const contentElem = messageDiv.querySelector('.content')
  const text = contentElem.innerText
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.classList.add('chat-input')
  messageDiv.replaceChild(textarea, contentElem)
  textarea.focus()
  textarea.onblur = () => {
    const newText = textarea.value
    messageDiv.replaceChild(contentElem, textarea)
    renderContent(newText, contentElem, roleLabel === 'User')
    // Update conversation if needed
  }
  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      textarea.blur()
    }
  })
}

function regenerateMessage(messageDiv) {
  // Find the previous user message
  const index = Array.from(messagesDiv.children).indexOf(messageDiv) - 1
  if (index >= 0) {
    const prev = messagesDiv.children[index]
    if (prev.classList.contains('user')) {
      sendMessage(prev.querySelector('.content').innerText)
    }
  }
}
function continueMessage() {
  if (lastUserMessage) {
    sendMessage('Continue the previous response.')
  }
}
function readAloud(text) {
  const utterance = new SpeechSynthesisUtterance(text)
  speechSynthesis.speak(utterance)
}

// ====================== SEND MESSAGE ======================
async function sendMessage(question, model = modelSelect.value) {
  lastUserMessage = question
  appendMessage('User', question)

  const grokDiv = appendMessage('Grok', 'Thinking...')

  let fullResponse = ''
  await streamApi(
    [{ role: 'user', content: question }],
    model,
    0.7,
    8192,
    true,
    currentChatId,
    data => {
      // Capture new chat_id and update URL + refresh history only once
      if (data.chat_id && !currentChatId) {
        currentChatId = data.chat_id
        updateUrlWithChatId(currentChatId)
        loadChatHistory() // only once when a brand new chat is created
      }

      const choice = data.choices?.[0]
      if (choice?.delta?.content) {
        fullResponse += choice.delta.content
        renderContent(fullResponse, grokDiv.querySelector('.content'))
      }
    })

  conversation.push({ role: 'user', content: question })
  conversation.push({ role: 'assistant', content: fullResponse })
  saveChat() // saves but does NOT refresh history every message
}

function handleSend() {
  if (input.value.trim()) {
    const question = input.value.trim()
    input.value = ''
    sendMessage(question)
  }
}

// ====================== EVENT LISTENERS ======================
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
})
input.addEventListener('input', () => {
  input.style.height = 'auto'
  input.style.height = `${input.scrollHeight}px`
})
sendBtn.onclick = handleSend
expertBtn.onclick = () => {
  if (lastUserMessage) sendMessage(lastUserMessage, 'grok-4-0709')
}

// ====================== INITIALISATION ======================
async function initApp() {
  const authenticated = await checkAuth()
  if (!authenticated) return

  // Load history ONCE and keep it in memory
  await loadChatHistory()

  // Load correct chat from URL
  const urlChatId = getChatIdFromUrl()
  if (urlChatId) {
    currentChatId = urlChatId
    await loadChat(urlChatId)
  } else {
    newChat()
  }

  // Browser back/forward
  window.addEventListener('popstate', () => {
    const id = getChatIdFromUrl()
    currentChatId = id
    if (id) loadChat(id)
    else newChat()
  })

  const chatRoot = document.querySelector('.chat-root')

  if (chatRoot) {
    // Function for adding target="_blank" to a single <a>
    function addBlankTarget(a) {
      a.setAttribute('target', '_blank')
    }

    // Function for replacing [something] with [domain] if it starts with '['
    function replaceWithDomain(a) {
      const text = a.textContent.trim()
      if (text.startsWith('[') && a.href) {
        try {
          const url = new URL(a.href)
          const domain = url.hostname.replace(/^(?:[^.]+\.)*([^.]+\.[^.]+)$/, '$1')
          a.textContent = `[${domain}]`
        } catch (e) {
          // Silent fail for invalid URLs
        }
      }
    }

    const observer = new MutationObserver(mutations => {
      mutations.forEach(mutation => {
        mutation.addedNodes.forEach(node => {
          if (node.nodeType === Node.ELEMENT_NODE) {
            node.querySelectorAll('a').forEach(a => {
              // Check if not processed (no target="_blank")
              if (a.getAttribute('target') !== '_blank') {
                addBlankTarget(a) // Apply mod 1
                replaceWithDomain(a) // Apply mod 2
              }
            })
          }
        })
      })
    })

    observer.observe(chatRoot, { childList: true, subtree: true })

    // Initial run on existing content
    chatRoot.querySelectorAll('a').forEach(a => {
      if (a.getAttribute('target') !== '_blank') {
        addBlankTarget(a)
        replaceWithDomain(a)
      }
    })
  }
}

window.onload = initApp
