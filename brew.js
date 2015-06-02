// TODO
// comment feedback on addition
// write none when reading sensor fails
// external temp display
// temp control

var graphInterval = 60;
var statusInterval = 5;
var lastDays = 24 * 3600 * 3; // zoom on last days data

// private
var running = false;
var selectedBrew = '';
var interval = null;
var activeBrew = null;
var refreshCounter = 0;
var rawdata = [];
var g = new Dygraph(document.getElementById("graph"), "", {
    rollPeriod: 10,
    showRoller: true,
});

updateStatus(true);

function post(url, cb, data) { ajax("POST", url, cb, data); }
function get(url, cb, data) { ajax("GET", url, cb, data); }
function ajax(method, url, cb, data) {
    if (typeof(data)==='undefined') data = null;
    var req;
    if (window.XMLHttpRequest) {
        // Firefox, Opera, IE7, and other browsers will use the native object
        req = new XMLHttpRequest();
    } else {
        // IE 5 and 6 will use the ActiveX control
        req = new ActiveXObject("Microsoft.XMLHTTP");
    }
    req.onreadystatechange = function () {
        if (req.readyState == 4) {
            if (req.status === 200 ||  // Normal http
                req.status === 0) {    // Chrome w/ --allow-file-access-from-files
                cb(req.responseText);
            }
        }
    };
    req.open(method, url, true);
    req.send(data);
}
function getSelectedName(name) {
    var select = document.getElementById(name);
    if (!select.length) return '';
    return select.options[select.selectedIndex].text;
}

function updateStatus(firstTime = false) {
    recvStatus.firstTime = firstTime;
    post('status', recvStatus);
    //, firstTime ? null : JSON.stringify({ 'tail': g.xAxisExtremes()[1] }));
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
                 $("#sensor_list td.value").eq(i).html('<b>' + sensor['curr'] + '</b>');
             }
        });
        if (!found) {
            $('#sensor_list').append(
                '<tr>'
                + '<td class=enabled><input type=checkbox class=enabled ' + (sensor['enabled'] ? 'checked=1' : '') + '/></td>'
                + '<td class=id>' + si + '</td>'
                + '<td class=value><b>' + sensor['curr'] + '</b></td>'
                + '<td><input class=min style="width:40px" type=text value="' + sensor['min'] + '"></td>'
                + '<td><input class=max style="width:40px" type=text value="' + sensor['max'] + '"></td>'
                + '<td><input class=name type=text value="' + sensor['name'] + '"></td>'
                + '</tr>');
            $('#comment_sensors').append('<option>' + sensor['name'] + '</option>');
        }
    }
    var u = $('#update');
    if (!u.is(':focus')) u.val(s['update']);
    var d = $('#date');
    if (!d.is(':focus')) d.val(s['date']);
    var u = $('#sync');
    if (!u.is(':focus')) u.val(s['sync']);

    var tail = s['tail'];
    if (tail && rawdata.length && running && selectedBrew == activeBrew) {
        for (var ti = 0; ti < tail.length; ++ti) {
            if (tail[ti][0] <= rawdata[rawdata.length - 1][0]) continue;

            rawdata.push(tail[ti]);
            g.rawData_ = rawdata;
            g.cascadeDataDidUpdateEvent_();
            g.predraw_();
            showLastDays();
            break;
        }
    }
}

function toggleConfig(el) { $('#config').toggle(el.checked); }
function visibilityChange(el) { g.setVisibility(el.id, el.checked); }
function tryShowLastDays() { if (!showLastDays()) setTimeout(tryShowLastDays, 10); }
function updateRunning() {
    if (selectedBrew != activeBrew) {
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
function removeBrew() {
    var n = getSelectedName("brewname");
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
        //g.updateOptions({ 'file': [] } );
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
function addComment() {
    $.post('comment', JSON.stringify({
        'sensor': getSelectedName('comment_sensors'),
        'comment': document.getElementById("comment").value,
     }), recvStatus);
}
function saveConfig() {
    var sdata = {};
    var table = document.getElementById("sensor_list");
    for (var i = 0, row; row = table.rows[i]; i++) {
        sdata[row.cells[1].innerHTML] = [
            row.cells[5].getElementsByClassName('name')[0].value,
            row.cells[0].getElementsByClassName('enabled')[0].checked,
            row.cells[3].getElementsByClassName('min')[0].value,
            row.cells[4].getElementsByClassName('max')[0].value,
            ];
    }
    // TODO - verify date
    data = { 'sensors': sdata,
            'update': $('#update').val(),
            'sync': $('#sync').val(),
            'date': $('#date').val(),
            'debug': document.getElementById("debug").checked,
            };
    $.post('status', JSON.stringify(data));
}
function shutdown(reboot) {
    if (!confirm('really shutdown/reboot ?')) return;
    $.post('status', JSON.stringify({ 'command': reboot ? 'reboot' : 'shutdown' }));
}
function showLastDays() {
    if (!lastDays) return;

    if (!running || selectedBrew != activeBrew) return true;

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
}
function loadBrew(bn) {
    selectedBrew = bn;
    get('data/' + bn + '.csv', loadBrewData);
}
function loadBrewData(csv) {
    // draw labels
    $('#labels').empty();
    var labels = document.getElementById("labels");
    var end = csv.indexOf('\n');
    if (end != -1) {
        var sl = csv.substring(0,end).split(',');
        for (var i = 1; i < sl.length; ++i) {
            var l = document.createElement("input");
            l.type = "checkbox";
            l.checked = true;
            l.id = i - 1;
            l.onclick = function(e) { visibilityChange(e.target); };
            labels.appendChild(l);

            var lt = document.createElement("label");
            lt.for = i - 1;
            lt.innerHTML = sl[i];
            labels.appendChild(lt);
        }
    }
    g.ready(brewReady);
    if (selectedBrew != activeBrew) g.updateOptions( { dateWindow : null }, true);
    g.rawData_ = g.parseCSV_(csv);
    g.cascadeDataDidUpdateEvent_();
    g.predraw_();
    rawdata = g.rawData_;
}
function brewReady() {

    /* g.setAnnotations([
    { series: "beer", x: "2014/12/01 17:59:18", shortText: "X", text: "DEMO"}
    ]); */

    setTimeout(tryShowLastDays, 10);

    if (interval) clearInterval(interval);
    interval = setInterval(function() {
        refreshCounter++;
        if ((refreshCounter % statusInterval) == 0) {
            updateStatus();
        }
    }, 1000);
}

