$(function () {
    "use strict";
    function log (x) {
        return x;
    }
    function makeEditable(o) {
        o.saveState = ko.observable('saved');
        o.editing = ko.observable(false);
        o.startEditing = function () {
            o.editing(true);
            try {
                o._backup = o.serialize();
            } catch (e) {

            }
        };
        o.stopEdit = function () {
            o.editing(false);
        };
        o.cancelEdit = function () {
            o.editing(false);
            o.cancel();
        };
        o.saveEdit = function () {
            o.editing(false);
            log(o);
            o.save();
        };
        return o;
    }
    function makeDataType(o, app) {
        var self = ko.mapping.fromJS(o),
            raw_fields = self.fields();
        self.fields = ko.observableArray([]);
        makeEditable(self);
        if (!o._id) {
            self._id = ko.observable();
        }
        self.view_link = ko.computed(function(){
            return TableViewUrl + "?table_id="+self._id();
        }, self);
        self.aboutToDelete = ko.observable(false);
        self.addField = function (data, event, o) {
            var i, field;
            if (o) {
                field = {
                    tag: ko.observable(o.tag),
                    with_props: ko.observable(o.with_props),
                    original_tag: ko.observable(o.tag),
                    is_new: ko.observable(false),
                    remove: ko.observable(false),
                    editing: ko.observable(false)
                };
            } else {
                field = {
                    tag: ko.observable(""),
                    with_props: ko.observable(false),
                    is_new: ko.observable(true),
                    remove: ko.observable(false),
                    editing: ko.observable(true)
                };
            }
            field.editTag = ko.computed({
                read: function () {
                    return field.tag();
                },
                write: function (tag) {
                    var j, noRepeats = true;
                    for (j = 0; j < self.fields().length; j += 1) {
                        if (self.fields()[j].tag === tag) {
                            noRepeats = false;
                        }
                    }
                    if (noRepeats) {
                        var oldTag = field.tag;
                        field.tag(tag);log(field);
                    }
                }
            });
            self.fields.push(field);
        };
        for (var i = 0; i < raw_fields.length; i += 1) {
            var tag = raw_fields[i].field_name();
            var with_props = (raw_fields[i].properties().length == 0) ? false : true; console.log(with_props);
            self.addField(undefined, undefined, {tag: tag, with_props: with_props});
        }

        self.save = function () {
            $.ajax({
                type: self._id() ? (self._destroy ? 'delete' : 'put') : 'post',
                url: UpdateTableUrl + (self._id() || ''),
                data: JSON.stringify(self.serialize()),
                dataType: 'json',
                success: function (data) {
                    self.saveState('saved');
                    if (!self._id()) {
                        self._id(data._id);
                    }
                    var indicesToRemoveAt = []
                    for (var i = 0; i < self.fields().length; i += 1) {
                        var field = self.fields()[i];
                        field.original_tag = field.tag;
                        field.is_new = false;
                        if (field.remove() == true){
                            indicesToRemoveAt.push(i);
                        }
                    }
                    for (var index in indicesToRemoveAt){
                        self.fields.remove(self.fields()[index]);
                    }
                    log(self);
                }
            });
            self.saveState('saving');
        };
        self.serialize = function () {
            return log({
                _id: self._id(),
                tag: self.tag(),
                view_link: self.view_link(),
                fields: (function () {
                    var fields = {}, i;
                    console.log(self.fields());
                    for (i = 0; i < self.fields().length; i += 1) {
                        var field = self.fields()[i];
                        var patch;
                        if (field.is_new) {
                            if (field.remove() == true) continue;
                            patch = {"is_new": 1};
                            fields[field.tag()] = patch;
                        }
                        else if (field.remove() === true) {
                            patch = {"remove": 1};
                            fields[field.original_tag] = patch;
                        }
                        else if (field.tag() !== field.original_tag){
                            patch = {"update": field.tag()};
                            fields[field.original_tag] = patch;
                        }
                        else {
                            patch = {};
                            fields[field.tag()] = patch;
                        }
                    }
                    return fields;
                }())
            });
        };
        return self;
    }
    function App() {
        var self = this;
        self.data_types = ko.observableArray([]);
        self.loading = ko.observable(0);
        self.selectedTables = ko.observableArray([]);

        self.updateSelectedTables = function(element, event) {
            var $elem = $(event.srcElement || event.currentTarget);
            var $checkboxes = $(".select-bulk");
            if ($elem.hasClass("toggle")){
                self.selectedTables.removeAll();
                if ($elem.data("all")) {
                    $.each($checkboxes, function() {
                        $(this).attr("checked", true);
                        self.selectedTables.push(this.value); 
                    });
                }
                else {
                    $.each($checkboxes, function() {
                        $(this).attr("checked", false);
                    });
                }
            }
            if ($elem.hasClass("select-bulk")) {
                var table_id = $elem[0].value;
                if ($elem[0].checked) {
                    self.selectedTables.push(table_id);
                }
                else {
                    self.selectedTables.splice(self.selectedTables().indexOf(table_id), 1);
                }
            }
        };

        self.downloadExcels = function(element, event) {
            var tables = [];
            var FixtureUrl = FixtureDownloadUrl;
            if (self.selectedTables().length < 1)
                return;
            for (var i in self.selectedTables()) {
                tables.push(self.selectedTables()[i]);
                FixtureUrl = FixtureUrl + "table_id=" + self.selectedTables()[i] + "&";
            }
            $("#fixture-download").modal();
            if (tables.length > 0){
                $.ajax({
                    url: FixtureUrl,
                    dataType: 'json',
                }).success(function (response) {
                    $("#downloading").hide();
                    $("#download-complete").show();
                    $("#file-download-url").attr("href", FixtureFileDownloadUrl + "download_id=" + response.download_id);
                });
            }
            
        };

        self.addDataType = function () {
            var dataType = makeDataType({
                tag: "",
                fields: ko.observableArray([])
            }, self);
            dataType.editing(true);
            self.data_types.push(dataType);
        };
        self.removeDataType = function (dataType) {
            if (confirm("Are you sure you want to delete the table '" + dataType.tag() + "'")){
                    dataType.save();                 
                    self.data_types.destroy(dataType);
            }
            return false;
        };
        self.loadData = function () {
            self.loading(self.loading() + 3);
            $.ajax({
                url: DataTypeUrl,
                type: 'get',
                dataType: 'json',
                success: function (data) {
                    var dataType;
                    for (var i = 0; i < data.length; i += 1) {
                        self.data_types.push(makeDataType(data[i], self));
                        dataType = self.data_types()[i];
                    }
                    self.loading(self.loading() - 1); log(data);
                }
            });
        };
    }
    function FileUpload() {
        this.file = ko.observable();
        var self = this;
        self.uploadExcels = function(element, event) {
            $("#uploadModal").modal({
                keyboard: false,
                backdrop: 'static'
            });
            $("#uploading").show();
            $("#uploadForm")[0].submit();
        };
    }

    var el = $('#fixtures-ui');
    var app = new App();
    ko.applyBindings(app, el.get(0));
    el.show();
    app.loadData();

    var uploadApp = new FileUpload();
    ko.applyBindings(uploadApp, $('#fixture-upload')[0]);

    $("#fixture-download").on("hidden", function(){
                    $("#downloading").show();
                    $("#download-complete").hide();
    });
});