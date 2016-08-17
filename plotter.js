binaryFillPlotter = function(e) {
  // Skip if we're drawing a single series for interactive highlight overlay.
  if (e.singleSeriesName) return;

  // We'll handle all the series at once, not one-by-one.
  if (e.seriesIndex !== 0) return;

  var g = e.dygraph;
  var setNames = g.getLabels().slice(1);  // remove x-axis

  // getLabels() includes names for invisible series, which are not included in
  // allSeriesPoints. We remove those to make the two match.
  for (var i = setNames.length; i >= 0; i--) {
    if (!g.visibility()[i]) setNames.splice(i, 1);
  }

  var cntSeriesFilled = 0;
  for (var i = 0; i < setNames.length; i++) {
    if (g.getBooleanOption("fillGraph", setNames[i])) ++cntSeriesFilled;
  }
  if (!cntSeriesFilled) return;
  // TODO - support for multiple switches

  var area = e.plotArea;
  var sets = e.allSeriesPoints;
  var setCount = sets.length;

  var fillAlpha = g.getNumericOption('fillAlpha');
  var colors = g.getColors();

  // process sets in reverse order (needed for stacked graphs)
  for (var setIdx = setCount - 1; setIdx >= 0; setIdx--) {
    var ctx = e.drawingContext;
    var setName = setNames[setIdx];
    if (!g.getBooleanOption('fillGraph', setName)) continue;

    var color = colors[setIdx];
    var axis = g.axisPropertiesForSeries(setName);
    var axisY = 1.0 + axis.minyval * axis.yscale;
    if (axisY < 0.0) axisY = 0.0;
    else if (axisY > 1.0) axisY = 1.0;
    axisY = area.h * axisY + area.y;

    var points = sets[setIdx];
    var iter = Dygraph.createIterator(points, 0, points.length,
        DygraphCanvasRenderer._getIteratorPredicate(
            g.getBooleanOption("connectSeparatedPoints", setName)));

    // should be same color as the lines but only 15% opaque.
    var rgb = Dygraph.toRGB_(color);
    var err_color =
        'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + fillAlpha + ')';
    ctx.fillStyle = err_color;
    ctx.lineWidth = 2.0;
    err_color =
        'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.9)';
    ctx.strokeStyle = err_color;
    ctx.beginPath();
    var last_x, is_first = true;

    // If the point density is high enough, dropping segments on their way to
    // the canvas justifies the overhead of doing so.
    if (points.length > 2 * g.width_) {
      ctx = DygraphCanvasRenderer._fastCanvasProxy(ctx);
    }

    var point;
    var prevX = NaN;
    var firstX = NaN;
    while (iter.hasNext) {
      point = iter.next();
      if (!Dygraph.isOK(point.y) || !point.yval) {
        if (isNaN(prevX)) continue;

        ctx.rect(firstX, 0, prevX - firstX, axisY);
        prevX = NaN;
        continue;
      }

      if (isNaN(prevX)) {
        firstX = point.canvasx;
      }
      prevX = point.canvasx;
    }

    if (isNaN(prevX)) {
      ctx.rect(firstX, 0, prevX - firstX, axisY);
    }

    ctx.fill();
    ctx.stroke();
  }
};

