// TODO
// new brew
// date setting
//
// sensors focus
// fix js legend
// update interval
// new/start/stop
// annotations

var graphInterval = 60;
var statusInterval = 5;
var lastDays = 24 * 3600 * 3; // zoom on last days data

// private
var bn = '';
var interval = null;
var activeBrew = null;
var refreshCounter = 0;
var g = new Dygraph(document.getElementById("graph"), "", {
    rollPeriod: 10,
    showRoller: true,
});

updateStatus(true);

function updateStatus(firstTime = false) {
    $.post('status', function(data) {
        if (!data.length) return; // TODO - handle bad data
        if (data[0] != '{') {
            alert(data);
            return;
        }
        var s = JSON.parse(data);
        var brewnames = $('#brewname  > option');
        for (var bi = 0; bi < s["brewfiles"].length; ++bi) {
            var bf = s["brewfiles"][bi];
            var found = false;
            brewnames.each(function(index) {
                if ($(this).text() == bf) found = true;
            });
            if (!found) $('#brewname').append('<option>' + bf + '</option>');
        }
        if (s["active"] != activeBrew) {
            activeBrew = s["active"];
            if (firstTime) {
                loadBrew(activeBrew);
                $('#brewname').val(activeBrew);
            }
        }
        var sensors = s["sensors"];
        for (var si in sensors) {
            var sensor = sensors[si];
            var found = false;
            $("#sensor_list td.id").each(function(i, tr) {
                 if ($(tr).html() == si) {
                     found = true;
                     $("#sensor_list td.value").eq(i).text(sensor[1]);
                 }
            });
            if (!found) $('#sensor_list').append(
                    '<tr><td class=id>' + si + '</td>'
                    + '<td class=value><b>' + sensor[1] + '</b></td>'
                    + '<td><input class=name type=text value="' + sensor[0] + '"></td></tr>')
        }
    });//.fail(function( jqXHR, textStatus, errorThrown ) { alert(textStatus); });;
}

function toggleSensors(el) { $('#sensors').toggle(el.checked); }
function visibilityChange(el) { g.setVisibility(el.id, el.checked); }
function tryShowLastDays() { if (!showLastDays()) setTimeout(tryShowLastDays, 10); }
function saveNames() {
    var data = {};
    var table = document.getElementById("sensor_list");
    for (var i = 0, row; row = table.rows[i]; i++) {
        data[row.cells[0].innerHTML] = row.cells[2].getElementsByClassName('name')[0].value;
    }
    $.post('status', JSON.stringify(data));
}
function showLastDays() {
    if (!lastDays) return;

    var d = g.xAxisExtremes()[1] - g.xAxisExtremes()[0];
    // FIXME - reset extremes
        //console.log(d);
    if (d == 1) return false;

    d /= 1000;
    if (d > lastDays) {
        g.updateOptions( { dateWindow :  [g.xAxisExtremes()[1] - lastDays * 1000, g.xAxisExtremes()[1]] });
    }
    return true;
}
function start() {
    $('#circle').css('background', 'green');
    $('#start').attr("disabled", true);
    $('#stop').removeAttr("disabled");
}
function stop() {
    $('#circle').css('background', 'red');
    $('#stop').attr("disabled", true);
    $('#start').removeAttr("disabled");
}
function brewChanged(e) {
    loadBrew(e.value);
    if (e.value != activeBrew) {
        $('#stop').attr("disabled", true);
        $('#start').attr("disabled", true);
        $('#circle').css('background', 'grey');
        g.updateOptions( { dateWindow : null });
    } else {
        // TODO
    }
}
function loadBrew(bn) {
    bn = 'data/' + bn + '.csv';

    g.ready(function() {
        // draw labels
        $('#labels').empty();
        var labels = document.getElementById("labels");
        var names = g.getLabels();
        for (var i = 1 ; i < names.length; ++i) {
            var l = document.createElement("input");
            l.type = "checkbox";
            l.checked = true;
            l.id = i - 1;
            l.onclick = function() { visibilityChange(l); }
            labels.appendChild(l);

            var lt = document.createElement("label");
            lt.for = i - 1;
            lt.innerHTML = names[i];
            labels.appendChild(lt);

        }

    /*
    g.setAnnotations([
    { series: "beer", x: "2014/12/01 17:59:18", shortText: "X", text: "DEMO"}
    ]);
    */
        setTimeout(tryShowLastDays, 10);

        if (interval) clearInterval(interval);
        interval = setInterval(function() {
            refreshCounter++;
            if ((refreshCounter % graphInterval) == 0) {
                g.ready(function() { showLastDays(g); });
                g.updateOptions({ 'file': bn } );
            }
            if ((refreshCounter % statusInterval) == 0) {
                updateStatus();
            }
        }, 1000);
    });

    g.updateOptions({ 'file': bn } );
}

