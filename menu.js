;(function (global) {
  "use strict";

  const { jQuery: $, QWebChannel, qt } = global
  let entries
  let input

  $(function() {
    const stubbedBridge = global.bridge = (function (console) {
      // Stub bridge implementation.  The real one is inject by Qt.
      return {
        accept_input () { console.log('tell menu to accept current input') },
        accept_selected () { console.log('tell menu to accept selected item') },
        alternate_pattern (pos) { console.log('tell menu to alternate pattern of word under cursor at position', pos) },
        clear () { console.log('tell menu to clear input') },
        complete (text) { console.log('send input to menu for completing', text) },
        dismiss () { console.log('tell menu to quit') },
        erase_word (pos) { console.log('tell menu to erase backward word from position', pos) },
        filter (text) { console.log('send input to menu for filtering', text) },
        filter_with_selected () { console.log('get selected value from menu') },
        redo () { console.log('tell menu to redo next undoable operation') },
        select_next () { console.log('tell menu to select next item') },
        select_next_from_history () { console.log('get next entry from history') },
        select_prev () { console.log('tell menu to select previous item') },
        select_prev_from_history () { console.log('get previous entry from history') },
        set_home () { console.log('tell menu to set home') },
        undo () { console.log('tell menu to undo last undoable operation') }
      };
    })(global.console)

    global.filterKeypressDelay = 0

    const menu = (function (methods) {
      let filterTimeout
      let filterText

      const forwarded = methods.reduce((bridge, method) => {
        bridge[method] = (...args) => global.bridge[method](...args)
        return bridge
      }, {})

      forwarded.sendText = function (text, complete) {
        const delay = global.filterKeypressDelay

        if (complete) {
          clearTimeout(filterTimeout)
          filterTimeout = null
          forwarded.complete(text)
          return
        }

        // accumulate filter calls which are not complete
        filterText = text
        if (filterTimeout) return

        filterTimeout = setTimeout(() => {
          filterTimeout = null
          forwarded.filter(filterText)
        }, delay)
      }

      return forwarded
    })(Object.keys(stubbedBridge))

    input = (function() {
      var self,
          _$el,
          currentMode

      $(window).on('focus', function() { $el().focus(); });

      return (self = {
        setup: function(callback) { callback($el()); },
        get: function() { return $el().val(); },
        overwrite: function(value) {
          if (value !== undefined) return $el().val(value).focus()
          else return $el().focus()
        },
        setCursor (pos) {
          const $field = $el()
          const field = $field.get(0)
          field.selectionStart = field.selectionEnd = pos
          $field.focus().change()
        },
        eraseWord: function() { menu.erase_word(cursor()) },
        alternatePattern: function() { menu.alternate_pattern(cursor()) },
        updateMode: function(prompt, newMode) {
          $('#prompt-box .prompt').text(prompt)

          if (currentMode) {
            $el().removeClass(currentMode + '-mode');
          }

          $el().addClass(newMode + '-mode').focus();
          currentMode = newMode;
        }
      });

      function $el() {
        return (_$el = _$el || $('#prompt-box .input'));
      }

      function cursor() {
        var field = $el().get(0);
        return field.selectionDirection == 'backward' ?
          field.selectionStart : field.selectionEnd;
      }
    })();

    entries = (function() {
      var _$box, _$el, _$sb;

      return {
        setup: function(callback) {
          $(window).on('resize', adjustHeight);
          adjustHeight();

          if (callback) {
            callback($el());
          }
        },

        select: function(index) {
          var $e = $el();
          $e.find('li.selected').removeClass('selected');
          ensureVisible(
            $e.find('li:nth-child(' + (index + 1) + ')').addClass('selected')
          );
        },

        update: function (filtered, total, items) {
          // if (total > 300000) global.filterKeypressDelay = 150
          // else if (total > 150000) global.filterKeypressDelay = 100
          // else global.filterKeypressDelay = 0

          $('#prompt-box .counters').text(`${filtered}/${total}`)

          set(items)

          if (items.length) {
            $('#prompt-box').removeClass('not-found')
          } else {
            $('#prompt-box').addClass('not-found')
          }

          if (filtered > items.length) {
            $('#prompt-box').addClass('over-limit')
          } else {
            $('#prompt-box').removeClass('over-limit')
          }
        }
      }

      function set (items) {
        var entries = items.map(function(item) {
          var $li = $(document.createElement('li'));

          if (item.data.icon) $li.append(`<img src="${item.data.icon}" />`)

          var title = '<p>' + item.partitions.map(function(partition) {
            return partition.unmatched +
              `<span class="match">${partition.matched}</span>`
          }).join('') + '</p>'

          $li.append(title)

          if (item.data.subtext) {
            $li.append(`<p class="subtext">${item.data.subtext}</p>`)
          }

          if (item.selected) $li.addClass('selected')

          return $li
        })

        $el().html(entries)
        adjustScroll()
      }

      function $box() {
        return (_$box = _$box || $('#entries-box'));
      }

      function $el() {
        return (_$el = _$el || (function() {
          return $('#entries').on('scroll', adjustScroll);
        })());
      }

      function $sb() {
        return (_$sb = _$sb || $('#scrollbar'));
      }

      function ensureVisible($item) {
        var top = $item.offset().top - $el().offset().top,
            eh = $box().height(),
            bottom = top + $item.outerHeight() - eh,
            current = $el().scrollTop(),
            scroll = current + (bottom >= 0 ? bottom : (top < 0 ? top : 0));

        $el().scrollTop(scroll);
      }

      function adjustHeight() {
        var height = $(window).height() - $box().offset().top;
        $box().height(height);
        $sb().outerHeight(height);
        adjustScroll();
      }

      function adjustScroll() {
        var visibleHeight = $box().height(), scroll = $el().scrollTop(),
            totalHeight = getTotalHeight();

        if (totalHeight > visibleHeight) {
          var thumbHeight = 100 * visibleHeight / totalHeight,
              top = 100 * scroll / totalHeight;

          $sb().find('.thumb').show().css({
            height: thumbHeight + '%',
            top: top + '%',
          });
        } else {
          $sb().find('.thumb').hide().css({ height: 0, top: 0 });
        }
      }

      function getTotalHeight() {
        return Array.prototype.slice.call(
          $el().find('> li').map(function(_, el) {
            return $(el).outerHeight();
          })
        ).reduce(function(a, b) { return a + b; }, 0);
      }
    })();

    const keyUpHandlers = {}
    const keyDownHandlers = {}

    keyUpHandlers.Enter = menu.accept_selected
    keyUpHandlers.Escape = menu.dismiss
    keyUpHandlers['Control-Enter'] = menu.accept_input
    keyUpHandlers['Control-Space'] = keyUpHandlers.Escape
    keyUpHandlers.Tab = function() {
      menu.sendText(input.get(), true)
    }

    ;['P', 'N'].forEach(function(k) {
      keyUpHandlers['Control-' + k] = function() { }
    })

    keyDownHandlers['Control-P'] = menu.select_prev_from_history
    keyDownHandlers['Control-N'] = menu.select_next_from_history
    keyDownHandlers['Control-H'] = menu.set_home
    keyDownHandlers['Control-J'] = menu.select_next
    keyDownHandlers['Control-K'] = menu.select_prev
    keyDownHandlers['Control-M'] = menu.filter_with_selected
    keyDownHandlers['Control-U'] = menu.clear
    keyDownHandlers['Control-W'] = input.eraseWord
    keyDownHandlers['Control-Y'] = menu.redo
    keyDownHandlers['Control-Z'] = menu.undo
    keyDownHandlers['Alt-P'] = input.alternatePattern

    input.setup(function($input) {
      $input.focus();
      $(document).on({
        'keydown': function(e) {
          var handler = keyDownHandlers[key(e)];
          if (handler) return swallow(e, handler);
        },

        'keyup': function(e) {
          (keyUpHandlers[key(e)] || (() => {}))()
        },

        'input': defaultHandler,

        'change': defaultHandler,

        'blur': function(e) {
          e.preventDefault();
          e.stopPropagation();
          return false;
        },
      });
    });

    entries.setup();

    function defaultHandler() {
      menu.sendText(input.get(), false);
    }

    function swallow(event, callback) {
      event.preventDefault();
      event.stopPropagation();
      callback();
      return false;
    }

    function key(event) {
      var mod = '';

      if (event.ctrlKey) mod += 'Control-';
      if (event.altKey) mod += 'Alt-';
      if (event.shiftKey) mod += 'Shift-';
      if (event.metaKey) mod += 'Meta-';

      return mod + keyName(event.keyCode);
    }

    function keyName(code) {
      switch (code) {
        case 8:  return 'Backspace';
        case 9:  return 'Tab';
        case 13: return 'Enter';
        case 16: return 'Shift';
        case 17: return 'Control';
        case 18: return 'Alt';
        case 27: return 'Escape';
        case 32: return 'Space';
        case 81: return 'Meta';
        default: return String.fromCharCode(code).toUpperCase();
      }
    }
  })

  new QWebChannel(qt.webChannelTransport, function (channel) {
    const bridge = global.bridge = channel.objects.bridge

    bridge.cursor.connect(input.setCursor)
    bridge.index.connect(entries.select)
    bridge.input.connect(input.overwrite)
    bridge.mode.connect(input.updateMode)
    bridge.update.connect(entries.update)

    bridge.js_ready()
  })
})(window)
