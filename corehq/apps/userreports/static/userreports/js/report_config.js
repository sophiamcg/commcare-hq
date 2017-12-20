/* global _, $, django, window */
var reportBuilder = function () {  // eslint-disable-line
    var self = this;

    var PropertyList = hqImport('userreports/js/builder_view_models').PropertyList;
    var PropertyListItem = hqImport('userreports/js/builder_view_models').PropertyListItem;
    var constants = hqImport('userreports/js/constants');

    var _kmq_track_click = function (action) {
        hqImport('analytix/js/kissmetrix').track.event("RBv2 - " + action);
    };

    var ColumnProperty = function (getDefaultDisplayText, getPropertyObject, reorderColumns, hasDisplayText) {
        PropertyListItem.call(this, getDefaultDisplayText, getPropertyObject, hasDisplayText);
        var self = this;
        this.inputBoundCalculation = ko.computed({
            read: function () {
                return self.calculation();
            },
            write: function (value) {
                self.calculation(value);
                if (window._bindingsApplied){
                    //reorderColumns();
                }
            },
            owner: this,
        });
    };
    ColumnProperty.prototype = Object.create(PropertyListItem.prototype);
    ColumnProperty.prototype.constructor = ColumnProperty;


    var ColumnList = function(options) {
        PropertyList.call(this, options);
        this.newProperty = ko.observable(null);
    };
    ColumnList.prototype = Object.create(PropertyList.prototype);
    ColumnList.prototype.constructor = ColumnList;
    ColumnList.prototype._createListItem = function () {
        return new ColumnProperty(
            this.getDefaultDisplayText.bind(this),
            this.getPropertyObject.bind(this),
            this.reorderColumns.bind(this),
            this.hasDisplayCol
        );
    };
    ColumnList.prototype.buttonHandler = function () {
        if (this.newProperty()) {
            var item = this._createListItem();
            item.property(this.newProperty());
            item.calculation(item.getDefaultCalculation());
            this.newProperty(null);
            this.columns.push(item);
            if (_.isFunction(this.addItemCallback)) {
                this.addItemCallback();
            }
        }
    };
    ColumnList.prototype.reorderColumns = function () {
        var items = {};

        // In the initialization of this.columns, reorderColumns gets called (because we set the calculation of
        // each ColumnProperty), but we don't want this function to run until the this.columns exists.
        if (this.columns) {
            this.columns().forEach(function (v, i) {
                items[[v.property(), v.calculation(), v.displayText()]] = i;
            });

            var isGroupBy = function (column) {
                return column.calculation() === constants.GROUP_BY;
            };
            var index = function (column) {
                return items[[column.property(), column.calculation(), column.displayText()]];
            };
            var compare = function (first, second) {
                // return negative if first is smaller than second
                if (isGroupBy(first) !== isGroupBy(second)) {
                    return isGroupBy(first) ? -1 : 1;
                }
                if (index(first) !== index(second)) {
                    return index(first) < index(second) ? -1 : 1;
                }
                return 0;
            };
            this.columns.sort(compare);
        }
    };


    /**
     * ReportConfig is a view model for managing report configuration
     */
    self.ReportConfig = function (config) {
        var self = this;

        self._mapboxAccessToken = config['mapboxAccessToken'];

        self._app = config['app'];
        self._sourceType = config['sourceType'];
        self._sourceId = config['sourceId'];

        self.dateRangeOptions = config['dateRangeOptions'];

        self.existingReportId = config['existingReport'];

        self.columnOptions = config["columnOptions"];  // Columns that could be added to the report
        self.reportPreviewUrl = config["reportPreviewUrl"];  // Fetch the preview data asynchronously.
        self.previewDatasourceId = config["previewDatasourceId"];

        self.reportTypeListLabel = (config['sourceType'] === "case") ? "Case List" : "Form List";
        self.reportTypeAggLabel = (config['sourceType'] === "case") ? "Case Summary" : "Form Summary";
        self.reportType = ko.observable(config['existingReportType'] || constants.REPORT_TYPE_LIST);
        self.reportType.subscribe(function (newValue) {
            _ga_track_config_change('Change Report Type', newValue);
            self._suspendPreviewRefresh = true;
            var wasAggregationEnabled = self.isAggregationEnabled();
            self.isAggregationEnabled(newValue === constants.REPORT_TYPE_TABLE);
            self.previewChart(newValue === constants.REPORT_TYPE_TABLE && self.selectedChart() !== "none");
            if (self.isAggregationEnabled() && !wasAggregationEnabled) {
                self.columnList.columns().forEach(function(val, index) {
                    if (index === 0) {
                        val.calculation(constants.GROUP_BY);
                    } else {
                        val.calculation(val.getDefaultCalculation());
                    }
                });
            }
            self._suspendPreviewRefresh = false;
            self.refreshPreview();
            self.saveButton.fire('change');
        });

        self.isAggregationEnabled = ko.observable(self.reportType() === constants.REPORT_TYPE_TABLE);

        self.selectedChart = ko.observable('none');
        self.selectedChart.subscribe(function (newValue) {
            if (newValue === "none") {
                self.previewChart(false);
            } else {
                if (self.previewChart()) {
                    hqImport('userreports/js/report_analytics').track.event('Change Chart Type', hqImport('hqwebapp/js/main').capitalize(newValue));
                }
                self.previewChart(true);
                self.refreshPreview();
            }
        });
        self.addChart = function () {
            self.selectedChart('bar');
            hqImport('userreports/js/report_analytics').track.event('Add Chart');
            _kmq_track_click('Add Chart');
        };
        self.removeChart = function () {
            self.selectedChart('none');
            hqImport('userreports/js/report_analytics').track.event('Remove Chart');
        };

        self.previewChart = ko.observable(false);
        self.tooManyChartCategoriesWarning = ko.observable(false);
        self.noChartForConfigWarning = ko.observable(false);

        self.previewChart.subscribe(function() {
            // Clear these warnings before revealing the chart div. This prevents them from flickering.
            // The warnings will be update in _renderChartPreview
            self.tooManyChartCategoriesWarning(false);
            self.noChartForConfigWarning(false);
        });

        /**
         * Convert the data source properties passed through the template
         * context into objects with the correct format for the select2 and
         * questionsSelect knockout bindings.
         * @param dataSourceIndicators
         * @private
         */
        var _getSelectableProperties = function (dataSourceIndicators) {
            var utils = hqImport('userreports/js/utils');
            if (self._optionsContainQuestions(dataSourceIndicators)) {
                return _.compact(_.map(
                    dataSourceIndicators, utils.convertDataSourcePropertyToQuestionsSelectFormat
                ));
            } else {
                return _.compact(_.map(
                    dataSourceIndicators, utils.convertDataSourcePropertyToSelect2Format
                ));
            }
        };

        var _getSelectableReportColumnOptions = function(reportColumnOptions, dataSourceIndicators) {
            var utils = hqImport('userreports/js/utils');
            if (self._optionsContainQuestions(dataSourceIndicators)) {
                return _.compact(_.map(
                    reportColumnOptions, utils.convertReportColumnOptionToQuestionsSelectFormat
                ));
            } else {
                return _.compact(_.map(
                    reportColumnOptions, utils.convertReportColumnOptionToSelect2Format
                ));
            }
        };

        var _ga_track_config_change = function (analyticsAction, optReportType) {
            var analyticsLabel = hqImport('hqwebapp/js/main').capitalize(self._sourceType) + "-" + hqImport('hqwebapp/js/main').capitalize(optReportType || self.reportType());
            hqImport('userreports/js/report_analytics').track.event(analyticsAction, analyticsLabel);
        };

        /**
         * Return true if the given data source indicators contain question indicators (as opposed to just meta
         * properties or case properties)
         * @param dataSourceIndicators
         * @private
         */
        self._optionsContainQuestions = function (dataSourceIndicators) {
            return _.any(dataSourceIndicators, function (o) {
                return o.type === 'question';
            });
        };

        self.location_field = ko.observable(config['initialLocation']);
        self.location_field.subscribe(function () {
            _kmq_track_click('Select Location (map)');
            self.refreshPreview();
        });

        self.optionsContainQuestions = self._optionsContainQuestions(config['dataSourceProperties']);
        self.selectablePropertyOptions = _getSelectableProperties(config['dataSourceProperties']);
        self.selectableReportColumnOptions = _getSelectableReportColumnOptions(self.columnOptions, config['dataSourceProperties']);

        self.columnList = new ColumnList({
            hasFormatCol: false,
            hasCalculationCol: self.isAggregationEnabled,
            initialCols: config['initialColumns'],
            reportType: self.reportType(),
            propertyOptions: self.columnOptions,
            selectablePropertyOptions: self.selectableReportColumnOptions,
            addItemCallback: function () {
                _ga_track_config_change('Add Column');
                _kmq_track_click('Add Column');
            },
            removeItemCallback: function () {
                _ga_track_config_change('Remove Column');
                _kmq_track_click('Delete Column');
            },
            reorderItemCallback: function () {
                _ga_track_config_change('Reorder Column');
            },
            afterRenderCallback: function (elem, col) {
                col.inputBoundCalculation.subscribe(function (val) {
                    hqImport('userreports/js/report_analytics').track.event('Change Format', val);
                });
            },
        });
        window.columnList = self.columnList;

        self.columnList.serializedProperties.subscribe(function (newValue) {
            self.refreshPreview(newValue);
            self.saveButton.fire('change');
        });

        self.filterList = new PropertyList({
            hasFormatCol: self._sourceType === "case",
            hasCalculationCol: false,
            initialCols: config['initialUserFilters'],
            buttonText: 'Add User Filter',
            addItemCallback: function () {
                _ga_track_config_change('Add User Filter');
                _kmq_track_click('Add User Filter');
            },
            removeItemCallback: function () {
                _ga_track_config_change('Remove User Filter');
                _kmq_track_click('Delete User Filter');
            },
            reorderItemCallback: function () {
                _ga_track_config_change('Reorder User Filter');
            },
            propertyHelpText: django.gettext('Choose the property you would like to add as a filter to this report.'),
            displayHelpText: django.gettext('Web users viewing the report will see this display text instead of the property name. Name your filter something easy for users to understand.'),
            formatHelpText: django.gettext('What type of property is this filter?<br/><br/><strong>Date</strong>: Select this if the property is a date.<br/><strong>Choice</strong>: Select this if the property is text or multiple choice.'),
            reportType: self.reportType(),
            propertyOptions: config['dataSourceProperties'],
            selectablePropertyOptions: self.selectablePropertyOptions,
        });
        self.filterList.serializedProperties.subscribe(function () {
            self.saveButton.fire("change");
        });
        self.defaultFilterList = new PropertyList({
            hasFormatCol: true,
            hasCalculationCol: false,
            hasDisplayCol: false,
            hasFilterValueCol: true,
            initialCols: config['initialDefaultFilters'],
            buttonText: 'Add Default Filter',
            addItemCallback: function () {
                _ga_track_config_change('Add Default Filter');
                _kmq_track_click('Add Default Filter');
            },
            removeItemCallback: function () {
                _ga_track_config_change('Remove Default Filter');
                _kmq_track_click('Delete Default Filter');
            },
            reorderItemCallback: function () {
                _ga_track_config_change('Reorder Default Filter');
            },
            propertyHelpText: django.gettext('Choose the property you would like to add as a filter to this report.'),
            formatHelpText: django.gettext('What type of property is this filter?<br/><br/><strong>Date</strong>: Select this to filter the property by a date range.<br/><strong>Value</strong>: Select this to filter the property by a single value.'),
            filterValueHelpText: django.gettext('What value or date range must the property be equal to?'),
            reportType: self.reportType(),
            propertyOptions: config['dataSourceProperties'],
            selectablePropertyOptions: self.selectablePropertyOptions,
        });
        self.defaultFilterList.serializedProperties.subscribe(function () {
            self.saveButton.fire("change");
        });
        self.previewError = ko.observable(false);
        self._suspendPreviewRefresh = false;
        self._pendingUpdate = false;
        self.refreshPreview = function (serializedColumns) {
            if (self._suspendPreviewRefresh) {
                self._pendingUpdate = true
            } else {
                self._suspendPreviewRefresh = true;
                self._pendingUpdate = false

                serializedColumns = typeof serializedColumns !== "undefined" ? serializedColumns : self.columnList.serializedProperties();
                $('#preview').hide();

                // Check if a preview should be requested from the server
                if (serializedColumns === "[]") {
                    return;  // Nothing to do.
                }
                $.ajax({
                    url: self.reportPreviewUrl,
                    type: 'post',
                    contentType: 'application/json; charset=utf-8',
                    data: JSON.stringify(Object.assign(
                        self.serialize(),
                        {
                            'app': self._app,
                            'source_type': self._sourceType,
                            'source_id': self._sourceId,
                        }
                    )),
                    dataType: 'json',
                    success: self.renderReportPreview,
                    success: function (data) {
                        self._suspendPreviewRefresh = false
                        if (self._pendingUpdate) {
                            self.refreshPreview();
                        } else {
                            self.renderReportPreview(data)
                        }
                    },
                    error: function () {
                        self._suspendPreviewRefresh = false
                        if (self._pendingUpdate) {
                            self.refreshPreview();
                        } else {
                            self.previewError(true)
                        }
                    },
                });
            }
        };

        // true if a map is being displayed. This is different than reportType === "map", because this is
        // only true if the preview function returned a mapSpec.
        self.displayMapPreview = ko.observable(false);

        self.renderReportPreview = function (data) {
            self.previewError(false);
            self.noChartForConfigWarning(false);
            self.tooManyChartCategoriesWarning(false);
            self._renderTablePreview(data['table']);
            self._renderChartPreview(data['chart_configs'], data['aaData']);
            self._renderMapPreview(data['map_config'], data["aaData"]);
        };

        self._renderMapPreview = function (mapSpec, aaData) {
            if (self.reportType() === "map" && mapSpec) {
                self.displayMapPreview(true);
                mapSpec.mapboxAccessToken = self._mapboxAccessToken;
                var render = hqImport('reports_core/js/maps').render;
                render(mapSpec, aaData, $("#map-preview-container"));
            } else {
                self.displayMapPreview(false);
            }
        };

        self._renderChartPreview = function (chartSpecs, aaData) {
            var charts = hqImport('reports_core/js/charts');
            if (chartSpecs !== null && chartSpecs.length > 0) {
                if (aaData.length > 25) {
                    self.tooManyChartCategoriesWarning(true);
                    charts.clear($("#chart-container"));
                } else {
                    charts.render(chartSpecs, aaData, $("#chart"));
                }
            } else {
                self.noChartForConfigWarning(true);
                charts.clear($("#chart"));
            }
        };

        self._renderTablePreview = function (data) {
            if (self.dataTable) {
                self.dataTable.destroy();
            }
            $('#preview').empty();
            self.dataTable = $('#preview').DataTable({
                "autoWidth": false,
                "ordering": false,
                "paging": false,
                "searching": false,
                "columns": _.map(data[0], function(column) { return {"title": column}; }),
                "data": data.slice(1),
            });
            $('#preview').show();
        };

        self.validate = function () {
            var isValid = true;
            if (!self.columnList.validate()) {
                isValid = false;
                $("#report-config-columns").collapse('show');
            }
            if (!self.filterList.validate()) {
                isValid = false;
                $("#report-config-userfilter").collapse('show');
            }
            if (!self.defaultFilterList.validate()) {
                isValid = false;
                $("#report-config-defaultfilters").collapse('show');
            }
            if (!isValid){
                alert('Invalid report configuration. Please fix the issues and try again.');
            }
            return isValid;
        };

        self.serialize = function () {
            return {
                "existing_report": self.existingReportId,
                "report_title": $('#report-title').val(), // From the inline-edit component
                "report_description": $('#report-description').val(),  // From the inline-edit component
                "report_type": self.reportType(),
                "aggregate": self.isAggregationEnabled(),
                "chart": self.selectedChart(),
                "columns": JSON.parse(self.columnList.serializedProperties()),
                "location": self.location_field(),
                "default_filters": JSON.parse(self.defaultFilterList.serializedProperties()),
                "user_filters": JSON.parse(self.filterList.serializedProperties()),
            };
        };

        var button = hqImport("hqwebapp/js/main").SaveButton;
        self.saveButton = button.init({
            unsavedMessage: "You have unsaved settings.",
            save: function () {
                var isValid = self.validate();
                _ga_track_config_change('Save Report');
                _kmq_track_click('Save Report');
                if (isValid) {
                    self.saveButton.ajax({
                        url: window.location.href,  // POST here; keep URL params
                        type: "POST",
                        data: JSON.stringify(self.serialize()),
                        dataType: 'json',
                        success: function (data) {
                            self.existingReportId = data['report_id'];
                        },
                    });
                }
            },
        });
        if (!config['previewMode']) {
            self.saveButton.ui.appendTo($("#saveButtonHolder"));
        }


        $("#btnSaveView").click(function () {
            var isValid = self.validate();
            if (isValid) {
                _ga_track_config_change('Save and View Report');
                _kmq_track_click('Save and View Report');
                $.ajax({
                    url: window.location.href,
                    type: "POST",
                    data: JSON.stringify(Object.assign(
                        self.serialize(),
                        {'delete_temp_data_source': true, 'preview_data_source_id': self.previewDatasourceId}
                    )),
                    success: function (data) {
                        // Redirect to the newly-saved report
                        self.saveButton.setState('saved');
                        window.location.href = data['report_url'];
                    },
                    dataType: 'json',
                });
            }
        });

        $('#deleteReport').click(function () {
            _ga_track_config_change('Delete Report');
            _kmq_track_click('Delete Report');
        });

        if (!self.existingReportId) {
            self.saveButton.fire('change');
        }
        self.refreshPreview(self.columnList.serializedProperties());
        if (config['initialChartType']) {
            self.selectedChart(config['initialChartType']);
        }
        return self;
    };

    return self;

}();
