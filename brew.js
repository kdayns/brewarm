// TODO
// lcd
// sensor min/max
// realtime update
// fix js legend
// annotations

var graphInterval = 60;
var statusInterval = 5;
var lastDays = 24 * 3600 * 3; // zoom on last days data

// private
var running = false;
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
    recvStatus.firstTime = firstTime;
    $.post('status', recvStatus);
    //.fail(function( jqXHR, textStatus, errorThrown ) { alert(textStatus); });;
}

function recvStatus(data) {
        if (!data.length) {
            console.log('no status data recv');
            return;
        }
        if (data[0] != '{') {
            document.getElementById("status").innerHTML = data;
            return;
        }
        document.getElementById("status").innerHTML = '';
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
        running = s['running'];
        if (s["active"] != activeBrew) {
            activeBrew = s["active"];
            if (recvStatus.firstTime) {
                loadBrew(activeBrew);
                $('#brewname').val(activeBrew);
            }
        }
        updateRunning();
        var sensors = s["sensors"];
        for (var si in sensors) {
            var sensor = sensors[si];
            var found = false;
            $("#sensor_list td.id").each(function(i, tr) {
                 if ($(tr).html() == si) {
                     found = true;
                     $("#sensor_list td.value").eq(i).html('<b>' + sensor[1] + '</b>');
                 }
            });
            if (!found) $('#sensor_list').append(
                    '<tr>'
                    + '<td class=enabled><input type=checkbox class=enabled ' + (sensor[3] ? 'checked=1' : '') + '/></td>'
                    + '<td class=id>' + si + '</td>'
                    + '<td class=value><b>' + sensor[1] + '</b></td>'
                    + '<td><input class=name type=text value="' + sensor[0] + '"></td>'
                    + '</tr>')
        }
        var u = $('#update');
        if (!u.is(':focus')) u.val(s['update']);
        var d = $('#date');
        if (!d.is(':focus')) d.val(s['date']);
}

function toggleConfig(el) { $('#config').toggle(el.checked); }
function visibilityChange(el) { g.setVisibility(el.id, el.checked); }
function tryShowLastDays() { if (!showLastDays()) setTimeout(tryShowLastDays, 10); }
function updateRunning() {
    if (getSelectedName() != activeBrew) {
        $('#stop').attr("disabled", true);
        $('#start').attr("disabled", true);
        $('#circle').css('background', 'grey');
        return;
    }
    if (running) {
        $('#start').attr("disabled", true);
        $('#stop').removeAttr("disabled");
        $('#circle').css('background', 'green');
    } else {
        $('#start').removeAttr("disabled");
        $('#stop').attr("disabled", true);
        $('#circle').css('background', 'red');
    }
}
function getSelectedName() {
    var select = document.getElementById("brewname");
    if (!select.length) return '';
    return select.options[select.selectedIndex].text;
}
function removeBrew() {
    var n = getSelectedName();
    if (!n.length) return;
    if (n == activeBrew) {
        alert('can\'t remove active brew!');
        return;
    }
    if (!confirm('really remove ' + n + '?')) return;

    select.remove(select.selectedIndex);
    if (select.length) {
        select.selectedIndex = 0;
        brewChanged(select.options[0].text);
    } else {
        $('#stop').attr("disabled", true);
        $('#start').attr("disabled", true);
        $('#circle').css('background', 'grey');
        g.updateOptions( { dateWindow : null });
        // TODO - clear graph
    }
    $.post('status', JSON.stringify({ 'command': 'kill', 'name': n }));
}
function newBrew() {
    var found = false;
    var table = document.getElementById("sensor_list");
    for (var i = 0, row; row = table.rows[i]; i++) {
        if (row.cells[0].getElementsByClassName('enabled')[0].checked) {
            found = true;
            break;
        }
    }
    if (!found) {
        alert('no sensors selected');
        return;
    }

    data = {}
    var name = prompt("new brew's name", 'brew_XX');
    data['active'] = name;
    data['running'] = true;
    $.post('status', JSON.stringify(data));
}
function saveConfig() {
    var sdata = {};
    var table = document.getElementById("sensor_list");
    for (var i = 0, row; row = table.rows[i]; i++) {
        sdata[row.cells[1].innerHTML] = [
            row.cells[3].getElementsByClassName('name')[0].value,
            row.cells[0].getElementsByClassName('enabled')[0].checked,
            ];
    }
    // TODO - verify date
    data = { 'sensors': sdata,
            'update': $('#update').val(),
            'date': $('#date').val(),
            };
    $.post('status', JSON.stringify(data));
}
function shutdown(reboot) {
    if (!confirm('really shutdown/reboot ?')) return;
    $.post('status', JSON.stringify({ 'command': reboot ? 'reboot' : 'shutdown' }));
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
    $.post('status', JSON.stringify({ 'running': true }), recvStatus);
}
function stop() {
    $.post('status', JSON.stringify({ 'running': false }), recvStatus);
}
function brewChanged(e) {
    loadBrew(e);
    updateRunning();
    if (e != activeBrew) g.updateOptions( { dateWindow : null });
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

