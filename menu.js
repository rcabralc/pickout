;(function (global) {
  const { jQuery: $, QWebChannel, qt } = global

  const bridge = global.bridge = (function (console) {
    // Stub bridge implementation.  The real one is inject by Qt.
    return {
      accept_input (input) { console.log('tell menu to accept input', input) },
      accept_selected () { console.log('tell menu to accept selected item') },
      complete (text) { console.log('send input to menu for completion', text) },
      dismiss () { console.log('tell menu to quit') },
      filter (seq, text) { console.log('send input to menu for filtering', seq, text) },
      request_next_from_history () { console.log('get next entry from history') },
      request_prev_from_history () { console.log('get previous entry from history') },
      select_next () { console.log('tell menu to select next item') },
      select_prev () { console.log('tell menu to select previous item') }
    }
  })(global.console)

  $(function () {
    const counters = buildCounters($('#prompt-box .counters')[0])
    const entries = buildEntries(
      $('#entries'),
      $('#entries-box'),
      $('#scrollbar')
    )
    const input = buildInput($('#prompt-box .input')[0])
    const menu = Object.keys(bridge).reduce((bridge, method) => {
      bridge[method] = (...args) => global.bridge[method](...args)
      return bridge
    }, {})
    const promptBox = buildPromptBox($('#prompt-box'), $('#prompt-box .prompt'))
    const widget = buildWidget({ counters, entries, input, menu, promptBox })

    new QWebChannel(qt.webChannelTransport, function (channel) {
      const bridge = global.bridge = channel.objects.bridge

      bridge.setup.connect(widget.setup)
      bridge.selected.connect(widget.select)
      bridge.filtered.connect(widget.update)
      bridge.history.connect(widget.history)
      bridge.completed.connect(widget.completed)

      bridge.js_ready()
    })
  })

  function buildCounters (el) {
    return {
      update (filtered, total) { el.innerText = `${filtered}/${total}` }
    }
  }

  function buildEntries ($el, $box, $sb) {
    $(window).on('resize', adjustHeight)
    $el.on('scroll', adjustScroll)
    adjustHeight()

    return { select, update }

    function adjustHeight() {
      const height = $(window).height() - $box.offset().top
      $box.height(height)
      $sb.outerHeight(height)
      adjustScroll()
    }

    function adjustScroll() {
      const visibleHeight = $box.height()
      const scroll = $el.scrollTop()
      const totalHeight = getTotalHeight()

      if (totalHeight > visibleHeight) {
        const thumbHeight = 100 * visibleHeight / totalHeight
        const top = 100 * scroll / totalHeight

        $sb.find('.thumb').show().css({
          height: thumbHeight + '%',
          top: top + '%',
        })
      } else {
        $sb.find('.thumb').hide().css({ height: 0, top: 0 })
      }
    }

    function ensureVisible($item) {
      const top = $item.offset().top - $el.offset().top
      const eh = $box.height()
      const bottom = top + $item.outerHeight() - eh
      const current = $el.scrollTop()
      $el.scrollTop(current + (bottom >= 0 ? bottom : (top < 0 ? top : 0)))
    }

    function getTotalHeight() {
      const heights = $el.find('> li').map((_, el) => $(el).outerHeight())
      return Array.from(heights).reduce((a, b) => a + b, 0)
    }

    function select (index) {
      $el.find('li.selected').removeClass('selected')
      ensureVisible(
        $el.find('li:nth-child(' + (index + 1) + ')').addClass('selected')
      )
    }

    function set (items) {
      const entries = items.map(item => {
        const $li = $(document.createElement('li'))

        if (item.data.icon) $li.append(`<img src="${item.data.icon}" />`)

        const title = '<p>' + item.partitions.map(({ unmatched, matched }) =>
          unmatched + `<span class="match">${matched}</span>`
        ).join('') + '</p>'

        $li.append(title)

        if (item.data.subtext) {
          $li.append(`<p class="subtext">${item.data.subtext}</p>`)
        }

        if (item.selected) $li.addClass('selected')

        return $li
      })

      $el.html(entries)
      adjustScroll()
    }

    function update (_filtered, _total, items) { set(items) }
  }

  function buildInput (el) {
    let delimiters = []
    let historyData
    let patternTypes = []

    $(window).on('focus', focus)
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
      getHistoryData,
      redo,
      resetHistoryData,
      set,
      setHistoryData,
      setup (params) {
        delimiters = params.delimiters || []
        if (!delimiters.includes(' ')) delimiters.push(' ')
        patternTypes = params.pattern_types || []
        el.value = params.input || ''
        el.dispatchEvent(new Event('input', { bubbles: true }))
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
      const nextPattern = found && patternTypes[i] || ''
      const currPattern = found && patternTypes[i - 1] || ''

      replace(nextPattern + word.slice(currPattern.length), start, end)
    }

    function eraseWord () {
      const end = getCursor() - 1
      const start = find(get(), end, -1, delimiters)
      replace('', start, end)
    }

    function find (value, index, step, delimiters) {
      while (
        index + step >= 0 && index + step < value.length &&
        !delimiters.includes(value[index + step])
      ) index = index + step
      return index
    }

    function focus (event) { if (!event || event?.target === el) el.focus() }

    function get () { return el.value }

    function getCursor () {
      return el.selectionDirection == 'backward'
        ? el.selectionStart
        : el.selectionEnd
    }

    function getHistoryData () { return historyData }

    function redo () { write(inputStack.redo()) }

    function replace (str, start, end) {
      const value = get()
      const newValue = value.slice(0, start) + str + value.slice(end + 1)
      set(newValue)
      el.selectionStart = start + str.length
      el.selectionEnd = el.selectionStart
    }

    function resetHistoryData () {
      historyData = { index: -1, value: el.value }
    }

    function set (value, { event = 'input' } = {}) {
      if (value == null) return
      inputStack.push(get(), write(value, { event }))
    }

    function setHistoryData ({ index, value }) {
      historyData.index = index
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

  function buildPromptBox ($box, $prompt) {
    return {
      setHistoryMode () {
        $prompt.removeClass('insert-mode').addClass('history-mode').text('◂')
      },
      setInserMode () {
        $prompt.removeClass('history-mode').addClass('insert-mode').text('▸')
      },
      update (filtered, _total, items) {
        if (items.length) {
          $box.removeClass('not-found')
        } else {
          $box.addClass('not-found')
        }

        if (filtered > items.length) {
          $box.addClass('over-limit')
        } else {
          $box.removeClass('over-limit')
        }
      }
    }
  }

  function buildWidget ({ counters, entries, input, menu, promptBox }) {
    let filterText = ''
    let filterTimeout = null
    let home = ''
    let pending = -1
    let selection
    let seq = -1

    setupEventHandlers()

    return { completed, history, setup, select, update }

    function completed (text) { input.set(text) }

    function filter ({ complete, inputEvent }) {
      if (inputEvent) {
        input.resetHistoryData()
        promptBox.setInserMode()
      }

      const text = input.get()

      if (complete) {
        clearTimeout(filterTimeout)
        filterTimeout = null
        menu.complete(text)
        return
      }

      // accumulate filter calls which are not complete
      filterText = text
      if (filterTimeout) return

      filterTimeout = setTimeout(() => {
        filterTimeout = null
        pending++
        menu.filter(++seq, filterText)
      }, pending * 500)
    }

    function history (index, value) {
      input.setHistoryData({ index, value })
      promptBox.setHistoryMode()
    }

    function select (index, value) {
      selection = { index, value }
      entries.select(index)
    }

    function setup (json) {
      const params = JSON.parse(json)
      home = params.home_input
      input.setup(params)
    }

    function setupEventHandlers () {
      const keyUpHandlers = {}
      const keyDownHandlers = {}

      keyUpHandlers.Enter = menu.accept_selected
      keyUpHandlers.Escape = menu.dismiss
      keyUpHandlers['Control-Enter'] = acceptInput
      keyUpHandlers['Control-Space'] = keyUpHandlers.Escape
      keyUpHandlers.Tab = complete

      keyDownHandlers['Control-P'] = requestPrevFromHistory
      keyDownHandlers['Control-N'] = requestNextFromHistory
      keyDownHandlers['Control-H'] = setHome
      keyDownHandlers['Control-J'] = menu.select_next
      keyDownHandlers['Control-K'] = menu.select_prev
      keyDownHandlers['Control-M'] = filterWithSelected
      keyDownHandlers['Control-U'] = clearInput
      keyDownHandlers['Control-W'] = input.eraseWord
      keyDownHandlers['Control-Y'] = input.redo
      keyDownHandlers['Control-Z'] = input.undo
      keyDownHandlers['Alt-P'] = input.alternatePattern

      function acceptInput () { menu.accept_input(input.get()) }
      function clearInput () { input.set('') }
      function complete () { filter({ complete: true, inputEvent: true }) }
      function filterWithSelected () {
        input.set(selection.value, { event: 'change' })
      }
      function handleInput () { filter({ complete: false, inputEvent: true }) }
      function handleChange () { filter({ complete: false, inputEvent: false }) }
      function requestNextFromHistory () {
        const { index, value } = input.getHistoryData()
        menu.request_next_from_history(index, value)
      }
      function requestPrevFromHistory () {
        const { index, value } = input.getHistoryData()
        menu.request_prev_from_history(index, value)
      }
      function setHome () { if (home) input.set(home) }

      function swallow(event, callback) {
        event.preventDefault()
        event.stopPropagation();
        callback()
        return false
      }

      function key(event) {
        let mod = ''

        if (event.ctrlKey) mod += 'Control-'
        if (event.altKey) mod += 'Alt-'
        if (event.shiftKey) mod += 'Shift-'
        if (event.metaKey) mod += 'Meta-'

        return mod + keyName(event.keyCode)
      }

      function keyName(code) {
        switch (code) {
          case 8:  return 'Backspace'
          case 9:  return 'Tab'
          case 13: return 'Enter'
          case 16: return 'Shift'
          case 17: return 'Control'
          case 18: return 'Alt'
          case 27: return 'Escape'
          case 32: return 'Space'
          case 81: return 'Meta'
          default: return String.fromCharCode(code).toUpperCase()
        }
      }

      $(document).on({
        'keydown': function (e) {
          const handler = keyDownHandlers[key(e)]
          if (handler) return swallow(e, handler)
        },
        'keyup': function (e) {
          (keyUpHandlers[key(e)] || (() => {}))()
        },
        'input': handleInput,
        'change': handleChange,
        'blur': function (e) {
          e.preventDefault()
          e.stopPropagation()
          return false
        }
      })
    }

    function update (receivedSeq, filtered, total, items) {
      pending--
      if (receivedSeq !== seq) return

      counters.update(filtered, total, items)
      entries.update(filtered, total, items)
      promptBox.update(filtered, total, items)
    }
  }
})(window)
