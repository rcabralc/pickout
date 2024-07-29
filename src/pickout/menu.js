;(function (global) {
	const { QWebChannel, qt } = global

	const bridge = global.bridge = (function (console) {
		// Stub bridge implementation.  The real one is inject by Qt.
		return {
			accept_input (input) { console.log('tell menu to accept input', input) },
			accept_selected () { console.log('tell menu to accept selected item') },
			complete (text) { console.log('send input to menu for completion', text) },
			dismiss () { console.log('tell menu to quit') },
			filter (seq, text) { console.log('send input to menu for filtering', seq, text) },
			refresh () { console.log('tell menu to refresh entries') },
			request_next_from_history () { console.log('get next entry from history') },
			request_prev_from_history () { console.log('get previous entry from history') },
			select_next () { console.log('tell menu to select next item') },
			select_prev () { console.log('tell menu to select previous item') }
		}
	})(global.console)

	function ready (callback) {
		if (document.readyState !== 'loading') callback()
		else document.addEventListener('DOMContentLoaded', callback)
	}

	ready(function () {
		const counters = buildCounters(document.querySelector('#prompt-box .counters'))
		const entries = buildEntries(document.getElementById('entries'), document.getElementById('entries-box'))
		const input = buildInput(document.querySelector('#prompt-box .input'))
		const menu = Object.keys(bridge).reduce((menu, method) => {
			menu[method] = (...args) => global.bridge[method](...args)
			return menu
		}, {})
		const progress = buildProgress(document.getElementsByTagName('progress')[0])
		const promptBox = buildPromptBox(document.getElementById('prompt-box'))
		const widget = buildWidget({ counters, entries, input, menu, progress, promptBox })

		new QWebChannel(qt.webChannelTransport, function (channel) {
			const bridge = global.bridge = channel.objects.bridge

			bridge.setup.connect(widget.setup)
			bridge.selected.connect(widget.select)
			bridge.filtered.connect(widget.update)
			bridge.history.connect(widget.history)
			bridge.completed.connect(widget.completed)
			bridge.picked.connect(widget.picked)
			bridge.themed.connect(widget.themed)

			bridge.js_ready()
		})
	})

	function buildCounters (el) {
		return {
			update (filtered, total) { el.innerText = `${filtered}/${total}` }
		}
	}

	function buildEntries (el, box) {
		window.addEventListener('resize', adjustScroll)
		el.addEventListener('scroll', adjustScroll)

		return { select, update }

		function adjustScroll() {
			const visibleHeight = window.innerHeight - box.getBoundingClientRect().top
			const table = el.getElementsByTagName('table')[0]
			if (!table) return

			const totalHeight = table.offsetHeight
			const totalHeightPx = `${totalHeight}px`

			box.style.setProperty('--visible-height', visibleHeight)
			box.style.setProperty('--total-height', totalHeight)
			box.style.setProperty('--scroll', el.scrollTop)

			if (totalHeight > visibleHeight) {
				box.style.setProperty('--sb-display', 'block')
			} else {
				box.style.setProperty('--sb-display', 'none')
			}
		}

		function ensureVisible (item) {
			const top = item.getBoundingClientRect().top - el.getBoundingClientRect().top
			const bottom = top + item.offsetHeight - box.clientHeight
			el.scrollTop += bottom >= 0 ? bottom : (top < 0 ? top : 0)
		}

		function select (index) {
			const newSelected = el.querySelector(`tr:nth-child(${index + 1})`)
			const oldSelected = el.querySelector(`tr.selected`)
			if (newSelected === oldSelected) return

			if (oldSelected) oldSelected.classList.remove('selected')
			if (!newSelected) return

			newSelected.classList.add('selected')
			ensureVisible(newSelected)
		}

		function set (items) {
			const entries = items.map(item => {
				const tr = document.createElement('tr')
				const cells = []

				if (item.data.icon) {
    				const img = document.createElement('img')
					img.setAttribute('src', item.data.icon)
					const cell = document.createElement('td')
					cell.classList.add('icon')
					cell.append(img)
					cells.push(cell)
				}

				if (item.data.subtext) {
					const cell = document.createElement('td')
					const title = document.createElement('p')

					item.partitions.forEach(({ unmatched, matched }) => {
						title.append(unmatched)
						const span = document.createElement('span')
						span.classList.add('match')
						span.append(matched)
						title.append(span)
					})

					cell.append(title)

					const subtext = document.createElement('p')
					subtext.classList.add('subtext')
					subtext.append(item.data.subtext)
					cell.append(subtext)

					cells.push(cell)
				} else {
					cells.push(document.createElement('td'))
					item.partitions.forEach(({ unmatched, matched }) => {
						unmatched.split('\t').forEach((text, i) => {
							if (i) cells.push(document.createElement('td'))
							cells[cells.length - 1].append(text)
						})
						matched.split('\t').forEach((text, i) => {
							if (i) cells.push(document.createElement('td'))
							const span = document.createElement('span')
							span.classList.add('match')
							span.append(text)
							cells[cells.length - 1].append(span)
						})
					})
				}

				cells[cells.length - 1].setAttribute('rolspan', Math.max(1, 11 - cells.length))
				if (item.selected) tr.classList.add('selected')

				tr.append(...cells)
				return tr
			})

			const table = document.createElement('table')
			table.append(...entries)
			el.replaceChildren(table)
			adjustScroll()
		}

		function update (_filtered, _total, items) { set(items) }
	}

	function buildInput (el) {
		let delimiters = []
		let historyState
		let isReady = false
		let patternTypes = []

		window.addEventListener('focus', focus)
		window.addEventListener('click', focus)
		el.focus()

		const inputStack = (function () {
			let pos = 0
			let inputs = []

			return { push, redo, undo }

			function push (oldValue, newValue) {
				inputs.splice(pos++, inputs.length, oldValue, newValue)
			}

			function redo () { return pos < inputs.length - 1 ? inputs[++pos] : null }
			function undo () { return pos ? inputs[--pos] : null }
		})()

		return {
			alternatePattern,
			eraseWord,
			get,
			getHistoryState,
			isReady () { return isReady },
			redo,
			resetHistoryState,
			set,
			setHistoryState,
			setup (params) {
				delimiters = params.delimiters || []
				if (!delimiters.includes(' ')) delimiters.push(' ')
				patternTypes = params.pattern_types || []
				el.value = (params.input || '') + el.value
				isReady = true
				el.dispatchEvent(new Event('input', { bubbles: true }))
			},
			picked () {
				el.value = ''
				isReady = false
			},
			undo
		}

		function alternatePattern () {
			const { word, start, end } = wordUnderCursor([' '])
			let i = 0
			let found = false

			while (i < patternTypes.length) if (word.startsWith(patternTypes[i++])) {
				found = true
				break
			}
			const nextPattern = found
				? patternTypes[i] || ''
				: patternTypes[0]
			const currPattern = found && patternTypes[i - 1] || ''

			replace(nextPattern + word.slice(currPattern.length), start, end)
		}

		function eraseWord () {
			const end = getCursor() - 1
			const text = get()
			let start = find(text, end, -1, delimiters)
			// Let only one delimiter character if there's a sequece of them.
			// For example, if delimiters are / and . (| is the cursor):
			//     foo/bar.baz| -> foo/bar.
			//     foo/...baz| -> foo/
			while (start >= 2 && delimiters.includes(text[start - 2])) start--
			replace('', start, end)
		}

		function find (value, index, step, delimiters) {
			while (
				index + step >= 0 && index + step < value.length &&
				!delimiters.includes(value[index + step])
			) index = index + step
			return index
		}

		function focus (event) { if (!event || event?.target !== el) el.focus() }

		function get () { return el.value }

		function getCursor () {
			return el.selectionDirection == 'backward'
				? el.selectionStart
				: el.selectionEnd
		}

		function getHistoryState () { return historyState }

		function redo () { write(inputStack.redo()) }

		function replace (str, start, end) {
			const value = get()
			const newValue = value.slice(0, start) + str + value.slice(end + 1)
			set(newValue)
			el.selectionStart = start + str.length
			el.selectionEnd = el.selectionStart
		}

		function resetHistoryState () {
			historyState = { index: -1, value: el.value }
		}

		function set (value, { event = 'input' } = {}) {
			if (value == null) return
			inputStack.push(get(), write(value, { event }))
		}

		function setHistoryState ({ index, value }) {
			historyState.index = index
			write(value)
		}

		function undo () { write(inputStack.undo()) }

		function wordUnderCursor (delimiters) {
			const value = get()
			const start = find(value, getCursor(), -1, delimiters)
			const end = find(value, start, 1, delimiters)
			return { start: start, end: end, word: value.slice(start, end + 1) }
		}

		function write (value, { event = 'change' } = {}) {
			if (value != null) el.value = value
			el.focus()
			el.dispatchEvent(new Event(event, { bubbles: true }))
			return value
		}
	}

	function buildProgress (progress) {
		return {
			start () { progress.classList.add('in-progress') },
			stop () { progress.classList.remove('in-progress') }
		}
	}

	function buildPromptBox (box) {
		const prompt = box.getElementsByClassName('prompt')[0]
		return {
			setHistoryMode () {
				prompt.classList.replace('insert-mode', 'history-mode')
				prompt.replaceChildren('◂')
			},
			setInserMode () {
				prompt.classList.replace('history-mode', 'insert-mode')
				prompt.replaceChildren('▸')
			},
			update (filtered, _total, items) {
				if (items.length) {
					box.classList.remove('not-found')
				} else {
					box.classList.add('not-found')
				}

				if (filtered > items.length) {
					box.classList.add('over-limit')
				} else {
					box.classList.remove('over-limit')
				}
			}
		}
	}

	function buildWidget ({ counters, entries, input, menu, progress, promptBox }) {
		let filterText = ''
		let filterTimeout = null
		let home = ''
		let pending = 0
		let selection
		let seq = -1

		setupEventHandlers()

		return { completed, history, picked, setup, select, themed, update }

		function completed (text) {
			input.set(text)
			progress.stop()
		}

		function filter ({ complete = false, inputEvent = true, refresh = false } = {}) {
			if (!input.isReady()) return

			progress.start()

			if (inputEvent) {
				input.resetHistoryState()
				promptBox.setInserMode()
			}

			const text = input.get()

			if (complete || refresh) {
				clearTimeout(filterTimeout)
				filterTimeout = null
				if (complete) menu.complete(text)
				else menu.refresh(text)
				return
			}

			// accumulate filter calls which are not complete
			filterText = text
			if (filterTimeout) return

			filterTimeout = setTimeout(() => {
				filterTimeout = null
				pending++
				menu.filter(++seq, filterText)
			}, pending * 50)
		}

		function history (index, value) {
			input.setHistoryState({ index, value })
			promptBox.setHistoryMode()
		}

		function picked () {
			input.picked()
		}

		function select (index, value) {
			selection = { index, value }
			entries.select(index)
		}

		function setup (json) {
			progress.start()
			const params = JSON.parse(json)
			home = params.home_input
			input.setup(params)
		}

		function setupEventHandlers () {
			const keyHandlers = {}

			keyHandlers.Enter = swallow(menu.accept_selected)
			keyHandlers.Escape = swallow(menu.dismiss)
			keyHandlers.Tab = swallow(complete)
			keyHandlers.F5 = swallow(refresh)
			keyHandlers['Control-Enter'] = swallow(acceptInput)
			keyHandlers['Control- '] = keyHandlers.Escape
			keyHandlers['Control-d'] = keyHandlers.Escape
			keyHandlers['Control-h'] = swallow(setHome)
			keyHandlers['Control-j'] = swallow(menu.select_next)
			keyHandlers['Control-k'] = swallow(menu.select_prev)
			keyHandlers['Control-m'] = swallow(filterWithSelected)
			keyHandlers['Control-n'] = swallow(requestNextFromHistory)
			keyHandlers['Control-p'] = swallow(requestPrevFromHistory)
			keyHandlers['Control-r'] = keyHandlers.F5
			keyHandlers['Control-u'] = swallow(clearInput)
			keyHandlers['Control-w'] = swallow(input.eraseWord)
			keyHandlers['Control-y'] = swallow(input.redo)
			keyHandlers['Control-z'] = swallow(input.undo)
			keyHandlers['Alt-p'] = swallow(input.alternatePattern)

			function acceptInput () { menu.accept_input(input.get()) }
			function clearInput () { input.set('') }
			function complete () { filter({ complete: true }) }
			function filterWithSelected () {
				input.set(selection.value, { event: 'change' })
			}
			function handleInput () { filter() }
			function handleChange () { filter({ inputEvent: false }) }
			function refresh () { filter({ refresh: true }) }
			function requestNextFromHistory () {
				const { index, value } = input.getHistoryState()
				menu.request_next_from_history(index, value)
			}
			function requestPrevFromHistory () {
				const { index, value } = input.getHistoryState()
				menu.request_prev_from_history(index, value)
			}
			function setHome () { if (home) input.set(home) }

			function swallow(callback) {
				return function (event) {
					event.preventDefault()
					event.stopPropagation()
					callback()
					return false
				}
			}

			function key(event) {
				let mod = ''

				if (event.ctrlKey) mod += 'Control-'
				if (event.altKey) mod += 'Alt-'
				if (event.shiftKey) mod += 'Shift-'
				if (event.metaKey) mod += 'Meta-'

				return mod + event.key
			}

			document.addEventListener('keydown', function (event) {
				return (keyHandlers[key(event)] || (() => {}))(event)
			})
			document.addEventListener('input', handleInput)
			document.addEventListener('change', handleChange)
			document.addEventListener('blur', function (event) {
				event.preventDefault()
				event.stopPropagation()
				return false
			})
		}

		function themed (themeVars) {
			const root = document.documentElement
			for (const [name, value] of themeVars) {
				root.style.setProperty(name, value)
			}
		}

		function update (receivedSeq, filtered, total, items) {
			pending--
			if (receivedSeq !== seq) return

			progress.stop()
			counters.update(filtered, total, items)
			entries.update(filtered, total, items)
			promptBox.update(filtered, total, items)
		}
	}
})(window)
