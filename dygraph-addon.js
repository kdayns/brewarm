binaryFillPlotter = function(e) {
  // Skip if we're drawing a single series for interactive highlight overlay.
  if (e.singleSeriesName) return;

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

        ctx.rect(firstX, 0, prevX - firstX, area.h);
        prevX = NaN;
        continue;
      }

      if (isNaN(prevX)) {
        firstX = point.canvasx;
      }
      prevX = point.canvasx;
    }

    if (isNaN(prevX)) {
      ctx.rect(firstX, 0, prevX - firstX, area.h);
    }

    ctx.fill();
    ctx.stroke();
  }
};

Dygraph.prototype.parseCSV_ = function(data) {
  var annotations = [];
  var ret = [];
  var line_delimiter = Dygraph.detectLineDelimiter(data);
  var lines = data.split(line_delimiter || "\n");
  var vals, j;

  // Use the default delimiter or fall back to a tab if that makes sense.
  var delim = this.getStringOption('delimiter');
  if (lines[0].indexOf(delim) == -1 && lines[0].indexOf('\t') >= 0) {
    delim = '\t';
  }

  var start = 0;
  if (!('labels' in this.user_attrs_)) {
    // User hasn't explicitly set labels, so they're (presumably) in the CSV.
    start = 1;
    this.attrs_.labels = lines[0].split(delim);  // NOTE: _not_ user_attrs_.
    this.attributes_.reparseSeries();
  }
  var line_no = 0;

  var xParser = Dygraph.dateParser;
  var expectedCols = this.attr_("labels").length;
  var outOfOrder = false;
  binarySeries = [];
  for (var i = start; i < lines.length; i++) {
    var line = lines[i];
    line_no = i;
    if (line.length === 0) continue;  // skip blank lines
    if (line[0] == '#') continue;    // skip comment lines
    var inFields = line.split(delim);
    if (inFields.length < 2) continue;

    var fields = [];
    fields[0] = xParser(inFields[0], this);

    {
      // Values are just numbers
      for (j = 1; j < inFields.length; j++) {
        var f = inFields[j];
        fields[j] = Dygraph.parseFloat_(f, i, line);
        if (typeof(fields[j]) == 'boolean') {
            fields[j] = fields[j] == true ? 1 : 0;
            binarySeries[j] = 1;
        }
      }
      // extract annotations
      // format: #<sensor num><wht space><comment>
      --j;
      var c = inFields[j].indexOf('#');
      if (c != -1) {
          c = inFields[j].substr(c + 1, inFields[j].length);
          var ann = {};
          var sidx = c.indexOf(' ');
          ann.text = c.substr(sidx + 1, c.length + sidx);
          ann.series = this.attrs_.labels[parseInt(c) + 1];
          ann.xval = fields[0];
          ann.shortText = annotations.length.toString();
          annotations.push(ann);
      }
    }
    if (ret.length > 0 && fields[0] < ret[ret.length - 1][0]) {
      outOfOrder = true;
    }

    if (fields.length != expectedCols) {
      console.error("Number of columns in line " + i + " (" + fields.length +
                    ") does not agree with number of labels (" + expectedCols +
                    ") " + line);
    }

    ret.push(fields);
  }

  if (ret.length) {
      var series = {}
      for (var j = 1; j < ret[0].length; j++) {
          if (!binarySeries[j]) continue;

          var n = this.attrs_.labels[j];
          series[n] = {
                fillGraph: true,
                highlightCircleSize: 0,
                plotter: binaryFillPlotter,
          };
      }
      this.updateOptions( { series }, true );
  }

  if (outOfOrder) {
    console.warn("CSV is out of order; order it correctly to speed loading.");
    ret.sort(function(a,b) { return a[0] - b[0]; });
  }

  this.setAnnotations(annotations, true);
  return ret;
}

Dygraph.parseFloat_ = function(x, opt_line_no, opt_line) {
  var val = parseFloat(x);
  if (!isNaN(val)) return val;

  // Try to figure out what happeend.
  // If the value is the empty string, parse it as null.
  if (/^ *$/.test(x)) return null;

  // If it was actually "NaN", return it as NaN.
  if (/^ *nan *$/i.test(x)) return NaN;

  // If it was bool
  if (/^false$/i.test(x)) return false;
  if (/^true$/i.test(x)) return true;

  // Looks like a parsing error.
  var msg = "Unable to parse '" + x + "' as a number";
  if (opt_line !== undefined && opt_line_no !== undefined) {
    msg += " on line " + (1+(opt_line_no||0)) + " ('" + opt_line + "') of CSV.";
  }
  console.error(msg);

  return null;
};
