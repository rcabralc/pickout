;(function (global) {
  "use strict";

  const { jQuery: $, QWebChannel, qt } = global

  const stubbedBridge = global.bridge = (function (console) {
    // Stub bridge implementation.  The real one is inject by Qt.

    return {
      filter: function(text, complete) {
        if (complete) {
          console.log('send input to menu for completing', text);
        } else {
          console.log('send input to menu for filtering', text);
        }
      },
      acceptInput: function() {
        console.log('tell menu to accept current input');
      },
      acceptSelected: function() {
        console.log('tell menu to accept selected item');
      },
      inputSelected: function() {
        console.log('get selected value from menu');
      },
      historyPrev: function() {
        console.log('get previous entry from history');
      },
      historyNext: function() {
        console.log('get next entry from history');
      },
      prev: function() {
        console.log('tell menu to select previous item');
      },
      next: function() {
        console.log('tell menu to select next item');
      },
      refresh: function () {
        console.log('tell menu to refresh entries')
      },
      dismiss: function() {
        console.log('tell menu to quit');
      }
    };
  })(global.console);

  global.filterKeypressDelay = 0

  const menu = (function (methods) {
    let filterTimeout
    let filterText

    const forwarded = methods.reduce((bridge, method) => {
      bridge[method] = (...args) => global.bridge[method](...args)
      return bridge
    }, {})

    forwarded.filter = function (text, complete) {
      const delay = global.filterKeypressDelay

      if (complete) {
        clearTimeout(filterTimeout)
        return filter(text, true)
      }

      // accumulate filter calls which are not complete
      filterText = text
      if (filterTimeout) return

      filterTimeout = setTimeout(() => { filter(filterText, false) }, delay)
    }

    return forwarded

    function filter (text, complete) {
      filterTimeout = null
      global.bridge.filter(text, complete)
    }
  })(Object.keys(stubbedBridge))

  let wordDelimiters

  global.frontend = {
    setInput: function(text) {
      input.overwrite(text);
    },

    setWordDelimiters: function(delimiters) {
      wordDelimiters = delimiters.split('')
    },

    updateMode: function(prompt, name) {
      $('#prompt-box .prompt').text(prompt)
      input.setMode(name)
    },

    update: function (filtered, total, items) {
      // if (total > 300000) global.filterKeypressDelay = 150
      // else if (total > 150000) global.filterKeypressDelay = 100
      // else global.filterKeypressDelay = 0

      $('#prompt-box .counters').text(`${filtered}/${total}`)

      entries.set(items)

      if (items.length) {
        input.markFound()
      } else {
        input.markNotFound()
      }

      if (filtered > items.length) {
        $('#prompt-box').addClass('over-limit')
      } else {
        $('#prompt-box').removeClass('over-limit')
      }
    },

    select: function(index) {
      entries.select(index);
    }
  }

  const input = (function() {
    var self,
        _$el,
        currentMode,
        patternTypes = ['@*', '@/'];

    $(window).on('focus', function() { $el().focus(); });

    return (self = {
      setup: function(callback) { callback($el()); },
      set: function(value) { $el().val(value).focus().change(); },
      get: function() { return $el().val(); },
      overwrite: function(value) { $el().val(value).focus(); },
      markFound: function() {
        $el().closest('#prompt-box').removeClass('not-found');
      },
      markNotFound: function() {
        $el().closest('#prompt-box').addClass('not-found');
      },
      clear: function() { self.set(''); },
      eraseWord: function() {
        var pos = cursor(),
            backpos = lookBackward(pos, wordDelimiters)
        if (backpos == pos && pos > 0) {
          backpos = lookBackward(pos - 1, wordDelimiters)
        }
        replace('', backpos, pos)
      },
      alternatePattern: function() {
        var w = wordUnderCursor(), word = w.value, i, pat;

        for (i = patternTypes.length - 1; i >= 0; i--) {
          pat = patternTypes[i];
          if (word.startsWith(pat)) {
            word = word.slice(pat.length);
            if (i == patternTypes.length - 1) {
              pat = '';
            } else {
              pat = patternTypes[i + 1];
            }
            word = pat + word;
            replace(word, w.start, w.end);
            return;
          }
        }

        word = patternTypes[0] + word;
        replace(word, w.start, w.end);
      },
      refresh: function() {
      },
      setMode: function(newMode) {
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

    function replace(str, start, end) {
      var $field = $el(), field = $field.get(0), value = $field.val();
      $field.val(value.slice(0, start) + str + value.slice(end + 1));
      field.selectionStart = start + str.length;
      field.selectionEnd = field.selectionStart;
      $field.focus();
    }

    function wordUnderCursor(delimiters) {
      var value = $el().val(),
          pos = cursor(),
          start, end;

      delimiters = delimiters || [' '];
      start = lookBackward(pos, delimiters);
      end = lookForward(start, delimiters);

      return { start: start, end: end, value: value.slice(start, end + 1) };
    }

    function lookBackward(pos, delimiters) {
      var start = pos, value = $el().val();
      while (start > 0) {
        if (delimiters.includes(value[start - 1])) break;
        start -= 1;
      }
      while (delimiters.includes(value[start])) start += 1;
      return start;
    }

    function lookForward(pos, delimiters) {
      var end = pos, value = $el().val();
      while (end < value.length - 1) {
        if (delimiters.includes(value[end])) break;
        end += 1;
      }
      while (delimiters.includes(value[end])) end -= 1;
      return end;
    }
  })();

  const entries = (function() {
    var _$box, _$el, _$sb;

    return {
      setup: function(callback) {
        $(window).on('resize', adjustHeight);
        adjustHeight();

        if (callback) {
          callback($el());
        }
      },

      set: function(items) {
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
        });

        $el().html(entries);
        adjustScroll();
      },

      select: function(index) {
        var $e = $el();
        $e.find('li.selected').removeClass('selected');
        ensureVisible(
          $e.find('li:nth-child(' + (index + 1) + ')').addClass('selected')
        );
      },
    };

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

  $(function() {
    var keyUpHandlers = {},
        keyDownHandlers = {};

    keyUpHandlers.Enter = menu.acceptSelected
    keyUpHandlers.Escape = menu.dismiss
    keyUpHandlers['Control-Enter'] = menu.acceptInput
    keyUpHandlers['Control-Space'] = keyUpHandlers.Escape;
    keyUpHandlers.Tab = function() {
      menu.filter(input.get(), true)
    };

    ['P', 'N'].forEach(function(k) {
      keyUpHandlers['Control-' + k] = function() { };
    });

    keyDownHandlers['Control-P'] = function() {
      menu.historyPrev()
    };
    keyDownHandlers['Control-N'] = function() {
      menu.historyNext()
    };
    keyDownHandlers['Control-J'] = function() { menu.next(); };
    keyDownHandlers['Control-K'] = function() { menu.prev(); };
    keyDownHandlers['Control-U'] = input.clear;
    keyDownHandlers['Control-W'] = input.eraseWord;
    keyDownHandlers['Control-Y'] = function() {
      menu.inputSelected()
    };
    keyDownHandlers['Alt-P'] = input.alternatePattern;
    keyDownHandlers['Control-R'] = function () {
      menu.refresh()
    }

    input.setup(function($input) {
      $input.focus();
      $(document).on({
        'keydown': function(e) {
          var handler = keyDownHandlers[key(e)];
          if (handler) return swallow(e, handler);
        },

        'keyup': function(e) {
          (keyUpHandlers[key(e)] || defaultHandler)();
        },

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
      menu.filter(input.get(), false);
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

    bridge.index.connect(frontend.select)
    bridge.input.connect(frontend.setInput)
    bridge.delimiters.connect(frontend.setWordDelimiters)
    bridge.mode.connect(frontend.updateMode)
    bridge.update.connect(frontend.update)

    bridge.js_ready()
  })
})(window)
